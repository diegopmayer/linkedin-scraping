from __future__ import annotations

import logging
import math
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobscan.adapters.store import DuckDbStore
from jobscan.application.classify import JobClassifier
from jobscan.application.collect import Collector, SearchCount, root_specs
from jobscan.application.fetch_details import DetailFetcher
from jobscan.application.ports import EligibilityLlm, Fetcher
from jobscan.application.report import ReportWriter
from jobscan.config import Settings
from jobscan.domain.errors import BlockedError, JobscanError, LockedError, MarkupChangedError

logger = logging.getLogger(__name__)

STAGES = ("collect", "details", "classify", "report", "done")
ASSUMED_TITLE_MATCH_RATIO = 0.35
ASSUMED_LLM_RATIO = 0.8
ASSUMED_COST_PER_LLM_CALL_USD = 0.00033
PARENT_FIRST_OVERHEAD = 1.3
EXIT_INTERRUPTED = 130

FetcherFactory = Callable[[str], Fetcher]
LlmFactory = Callable[[], EligibilityLlm | None]


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    exit_code: int
    status: str
    report_dir: Path | None
    message: str = ""


@dataclass(frozen=True)
class Estimate:
    count_requests: int
    list_requests: int
    detail_requests: int
    llm_calls: int
    hours: float
    llm_cost_usd: float

    def describe(self) -> str:
        return (
            f"Rough estimate: ~{self.count_requests} count + ~{self.list_requests} list + ~{self.detail_requests} "
            f"detail requests ≈ {self.hours:.1f} h at the configured delay; ~{self.llm_calls} LLM calls "
            f"≈ ${self.llm_cost_usd:.2f} (assumes {int(ASSUMED_TITLE_MATCH_RATIO * 100)}% of collected titles "
            "match a role; cached pages and LLM answers make reruns much faster)."
        )


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def estimate(counts: list[SearchCount], settings: Settings) -> Estimate:
    cap = settings.app.slicing.cap
    count_requests = list_requests = details = 0
    for item in counts:
        value = item.count.value if item.count and item.count.value is not None else cap
        capped = item.count is None or item.count.is_lower_bound or value >= cap
        list_requests += math.ceil(value / 10 * (PARENT_FIRST_OVERHEAD if capped else 1.0))
        count_requests += 1 + (10 if capped else 0)
        details += int(value * ASSUMED_TITLE_MATCH_RATIO)
    http = settings.app.http
    mean_delay = (http.min_delay_seconds + http.max_delay_seconds) / 2
    total = count_requests + list_requests + details
    llm_calls = int(details * ASSUMED_LLM_RATIO) if settings.app.llm.enabled else 0
    return Estimate(count_requests, list_requests, details, llm_calls, total * mean_delay / 3600,
                    llm_calls * ASSUMED_COST_PER_LLM_CALL_USD)


@contextmanager
def run_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip() or "0")
        except ValueError:
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise LockedError(f"another jobscan process (pid {pid}) is running; lock file {lock_path}")
    lock_path.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        store: DuckDbStore,
        *,
        fetcher_factory: FetcherFactory,
        llm_factory: LlmFactory,
        progress: Callable[[str], None] = print,
    ) -> None:
        self._settings = settings
        self._store = store
        self._fetcher_factory = fetcher_factory
        self._llm_factory = llm_factory
        self._progress = progress

    def _lock(self) -> Any:
        return run_lock(self._settings.path(self._settings.app.paths.database).parent / ".jobscan.lock")

    def count(self, *, roles: set[str] | None, countries: set[str] | None) -> tuple[str, list[SearchCount], Path]:
        run_id = new_run_id()
        with self._lock():
            self._store.create_run(run_id, mode="count", config_hash=self._settings.config_hash(),
                                   roles=",".join(sorted(roles)) if roles else None,
                                   countries=",".join(sorted(countries)) if countries else None)
            fetcher = self._fetcher_factory(run_id)
            counts = Collector(self._settings, self._store, fetcher, run_id).count_only(
                root_specs(self._settings, roles=roles, countries=countries))
            self._store.update_run(run_id, status="completed", stage="done",
                                   finished_at=datetime.now(timezone.utc).replace(tzinfo=None))
            self._store.add_run_counters(run_id, request_count=fetcher.request_count)
            out = self._settings.path(self._settings.app.paths.reports_dir) / run_id
            self._store.export_csv(
                [{"role": c.role, "country": c.country, "keywords": c.keywords,
                  "displayed_count_raw": c.count.raw if c.count else None,
                  "displayed_count": c.count.value if c.count else None,
                  "is_lower_bound": c.count.is_lower_bound if c.count else None} for c in counts],
                out / "counts.csv",
            )
        return run_id, counts, out

    def run(
        self,
        *,
        resume: bool,
        refresh: bool,
        roles: set[str] | None,
        countries: set[str] | None,
        include_unclear: bool,
    ) -> RunOutcome:
        with self._lock():
            run_id, stage = self._start_or_resume(resume=resume, roles=roles, countries=countries)
            run_row = self._store.get_run(run_id) or {}
            roles = set(run_row["roles_filter"].split(",")) if run_row.get("roles_filter") else roles
            countries = set(run_row["countries_filter"].split(",")) if run_row.get("countries_filter") else countries
            fetcher = self._fetcher_factory(run_id)
            llm = self._llm_factory()
            try:
                return self._execute(run_id, stage, fetcher, llm, refresh=refresh, roles=roles,
                                     countries=countries, include_unclear=include_unclear)
            except BlockedError as exc:
                return self._stop(run_id, "paused", exc.exit_code, f"{exc}. Resume later with `jobscan run --resume`.",
                                  fetcher, llm)
            except MarkupChangedError as exc:
                return self._stop(run_id, "failed", exc.exit_code, str(exc), fetcher, llm)
            except KeyboardInterrupt:
                return self._stop(run_id, "paused", EXIT_INTERRUPTED,
                                  "interrupted; resume with `jobscan run --resume`", fetcher, llm)
            except JobscanError as exc:
                return self._stop(run_id, "failed", exc.exit_code, str(exc), fetcher, llm)

    def _start_or_resume(
        self, *, resume: bool, roles: set[str] | None, countries: set[str] | None
    ) -> tuple[str, str]:
        if resume:
            previous = self._store.latest_resumable_run("run")
            if previous is not None:
                self._store.update_run(previous["run_id"], status="running", message=None)
                self._progress(f"Resuming run {previous['run_id']} at stage '{previous['stage']}'")
                return previous["run_id"], previous["stage"]
            self._progress("No paused or failed run found; starting a new run")
        run_id = new_run_id()
        self._store.create_run(run_id, mode="run", config_hash=self._settings.config_hash(),
                               roles=",".join(sorted(roles)) if roles else None,
                               countries=",".join(sorted(countries)) if countries else None)
        return run_id, "collect"

    def _record_counters(self, run_id: str, fetcher: Fetcher, llm: EligibilityLlm | None) -> None:
        increments = {"request_count": getattr(fetcher, "request_count", 0),
                      "error_count": getattr(fetcher, "error_count", 0)}
        if llm is not None:
            increments.update(llm_calls=getattr(llm, "calls_made", 0),
                              llm_input_tokens=getattr(llm, "input_tokens", 0),
                              llm_output_tokens=getattr(llm, "output_tokens", 0),
                              llm_cache_read_tokens=getattr(llm, "cache_read_tokens", 0))
        self._store.add_run_counters(run_id, **increments)
        for attr in ("request_count", "error_count"):
            if hasattr(fetcher, attr):
                setattr(fetcher, attr, 0)
        if llm is not None:
            for attr in ("calls_made", "input_tokens", "output_tokens", "cache_read_tokens"):
                if hasattr(llm, attr):
                    setattr(llm, attr, 0)

    def _stop(
        self, run_id: str, status: str, code: int, message: str, fetcher: Fetcher, llm: EligibilityLlm | None
    ) -> RunOutcome:
        self._record_counters(run_id, fetcher, llm)
        self._store.update_run(run_id, status=status, message=message)
        self._progress(f"Run {run_id} {status}: {message}")
        return RunOutcome(run_id, code, status, None, message)

    def _execute(
        self,
        run_id: str,
        stage: str,
        fetcher: Fetcher,
        llm: EligibilityLlm | None,
        *,
        refresh: bool,
        roles: set[str] | None,
        countries: set[str] | None,
        include_unclear: bool,
    ) -> RunOutcome:
        start_index = STAGES.index(stage) if stage in STAGES else 0
        specs = root_specs(self._settings, roles=roles, countries=countries)
        collector = Collector(self._settings, self._store, fetcher, run_id, progress=self._progress)

        if start_index <= STAGES.index("collect"):
            counts = collector.count_only(specs)
            self._progress(estimate(counts, self._settings).describe())
            collector.collect(specs)
            self._advance(run_id, "details", fetcher, llm)
        if start_index <= STAGES.index("details"):
            stats = DetailFetcher(self._store, fetcher, run_id, progress=self._progress).run(
                refresh=refresh, roles=roles)
            self._progress(f"Details: {stats.ok} ok, {stats.missing} missing, {stats.from_cache} from cache")
            self._advance(run_id, "classify", fetcher, llm)
        message = ""
        if start_index <= STAGES.index("classify"):
            result = JobClassifier(self._settings, self._store, run_id, llm, progress=self._progress).run(roles=roles)
            self._progress(f"Classified {result.classified}: {result.by_label}")
            reason = getattr(llm, "disabled_reason", None) if llm is not None else "LLM turned off"
            if reason or result.llm_skipped_unavailable:
                message = (f"LLM unavailable for {result.llm_skipped_unavailable} jobs ({reason or 'budget reached'});"
                           " those jobs are UNCLEAR. Fix it and run `jobscan reclassify`.")
            violations = self._store.quality_violations(run_id)
            if any(violations.values()):
                raise JobscanError(f"data quality gate failed: {violations}")
            self._advance(run_id, "report", fetcher, llm)
        if message:
            self._store.update_run(run_id, message=message)
        self._store.update_run(run_id, status="completed", stage="done",
                               finished_at=datetime.now(timezone.utc).replace(tzinfo=None))
        report_dir = ReportWriter(self._settings, self._store).write(run_id, include_unclear=include_unclear)
        self._progress(f"Report: {report_dir / 'report.md'}")
        return RunOutcome(run_id, 0, "completed", report_dir, message)

    def _advance(self, run_id: str, stage: str, fetcher: Fetcher, llm: EligibilityLlm | None) -> None:
        self._record_counters(run_id, fetcher, llm)
        self._store.update_run(run_id, stage=stage)

    def report(self, run_id: str | None, *, include_unclear: bool) -> Path:
        target = run_id or (self._store.latest_run("run") or {}).get("run_id")
        if not target:
            raise JobscanError("no run found; run `jobscan run` first")
        return ReportWriter(self._settings, self._store).write(target, include_unclear=include_unclear)

    def reclassify(self, run_id: str | None, *, include_unclear: bool) -> tuple[str, Path]:
        target = run_id or (self._store.latest_run("run") or {}).get("run_id")
        if not target:
            raise JobscanError("no run found; run `jobscan run` first")
        with self._lock():
            removed = self._store.clear_classifications(target)
            self._progress(f"Removed {removed} classifications of run {target}; classifying again")
            llm = self._llm_factory()
            run_row = self._store.get_run(target) or {}
            roles = set(run_row["roles_filter"].split(",")) if run_row.get("roles_filter") else None
            result = JobClassifier(self._settings, self._store, target, llm, progress=self._progress).run(roles=roles)
            self._progress(f"Classified {result.classified}: {result.by_label}")
            if llm is not None:
                self._store.add_run_counters(target, llm_calls=getattr(llm, "calls_made", 0),
                                             llm_input_tokens=getattr(llm, "input_tokens", 0),
                                             llm_output_tokens=getattr(llm, "output_tokens", 0),
                                             llm_cache_read_tokens=getattr(llm, "cache_read_tokens", 0))
            return target, ReportWriter(self._settings, self._store).write(target, include_unclear=include_unclear)
