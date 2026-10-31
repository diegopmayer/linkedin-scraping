from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from jobscan.adapters.store import DuckDbStore
from jobscan.application.ports import EligibilityLlm
from jobscan.config import Settings
from jobscan.domain.eligibility import RestrictionScanner, decide
from jobscan.domain.models import Eligibility, Method, RemoteStatus
from jobscan.domain.remote import RemoteClassifier
from jobscan.domain.technologies import TechExtractor

logger = logging.getLogger(__name__)
PROGRESS_EVERY = 50


@dataclass
class ClassifyStats:
    classified: int = 0
    by_label: dict[str, int] = field(default_factory=dict)
    by_method: dict[str, int] = field(default_factory=dict)
    llm_skipped_unavailable: int = 0


class JobClassifier:
    def __init__(
        self,
        settings: Settings,
        store: DuckDbStore,
        run_id: str,
        llm: EligibilityLlm | None,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._run_id = run_id
        self._llm = llm
        self._scanner = RestrictionScanner(settings.eligibility)
        self._remote = RemoteClassifier(settings.remote)
        self._techs = TechExtractor(settings.technologies.technologies)
        self._progress = progress or (lambda message: None)
        self.rules_version = f"{settings.eligibility.rules_version}+{settings.remote.rules_version}"

    def _llm_available(self) -> bool:
        return self._llm is not None and bool(getattr(self._llm, "available", True))

    def run(self, *, roles: set[str] | None = None) -> ClassifyStats:
        tech_ids = self._store.sync_technologies(self._techs.canonicals)
        jobs = self._store.jobs_to_classify(self._run_id, roles=roles)
        stats = ClassifyStats()
        min_conf = self._settings.app.llm.min_confidence_latam
        for index, job in enumerate(jobs, start=1):
            text = job.description_text or ""
            remote = self._remote.classify(text)
            matches = self._scanner.scan(text)
            verdict = None
            has_clear = any(m.is_clear for m in matches)
            if not has_clear and self._llm is not None:
                verdict = self._llm.classify(
                    title=job.title, location=job.location_text, description=text,
                    hints=self._scanner.hints(text, matches),
                )
                if verdict is None and not self._llm_available():
                    stats.llm_skipped_unavailable += 1
            result = decide(
                matches=matches, verdict=verdict, description=text,
                llm_available=verdict is not None, min_confidence=min_conf,
            )
            if remote is RemoteStatus.UNKNOWN and verdict is not None:
                remote = RemoteStatus(verdict.work_arrangement)
            used_llm = result.method is Method.LLM
            self._store.put_classification(
                job_id=job.job_id, run_id=self._run_id, remote=remote, result=result,
                rules_version=self.rules_version,
                prompt_version=self._llm.prompt_version if used_llm and self._llm else None,
                llm_model=self._llm.model if used_llm and self._llm else None,
                reasoning=verdict.reasoning_short if verdict is not None and used_llm else None,
            )
            self._store.put_job_technologies(job.job_id, self._techs.extract(text), tech_ids)
            stats.classified += 1
            stats.by_label[result.label.value] = stats.by_label.get(result.label.value, 0) + 1
            stats.by_method[result.method.value] = stats.by_method.get(result.method.value, 0) + 1
            if result.label is Eligibility.LATAM_FRIENDLY:
                logger.info("LATAM-friendly: %s %s", job.job_id, job.title)
            if index % PROGRESS_EVERY == 0 or index == len(jobs):
                self._progress(f"classified {index}/{len(jobs)} {stats.by_label}")
        return stats
