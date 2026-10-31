from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from jobscan.adapters import linkedin
from jobscan.adapters.store import DuckDbStore
from jobscan.application.ports import Fetcher
from jobscan.domain.errors import MarkupChangedError

logger = logging.getLogger(__name__)
MIN_SAMPLE_FOR_MARKUP_CHECK = 20
MAX_EMPTY_DESCRIPTION_RATIO = 0.2
PROGRESS_EVERY = 25


@dataclass
class DetailStats:
    attempted: int = 0
    ok: int = 0
    missing: int = 0
    empty_description: int = 0
    from_cache: int = 0


class DetailFetcher:
    def __init__(
        self,
        store: DuckDbStore,
        fetcher: Fetcher,
        run_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._store = store
        self._fetcher = fetcher
        self._run_id = run_id
        self._progress = progress or (lambda message: None)

    def run(self, *, refresh: bool = False, roles: set[str] | None = None) -> DetailStats:
        job_ids = self._store.jobs_needing_details(self._run_id, refresh=refresh, roles=roles)
        stats = DetailStats()
        total = len(job_ids)
        for index, job_id in enumerate(job_ids, start=1):
            stats.attempted += 1
            result = self._fetcher.get(linkedin.detail_url(job_id), cache_scope="global", force=refresh)
            stats.from_cache += int(result.from_cache)
            if result.status != 200:
                stats.missing += 1
                self._store.put_detail(None, job_id=job_id, http_status=result.status, html="")
            else:
                detail = linkedin.parse_detail(job_id, result.body)
                if not detail.description_text:
                    stats.empty_description += 1
                self._store.put_detail(detail, job_id=job_id, http_status=result.status, html=result.body)
                stats.ok += 1
            self._check_markup(stats)
            if index % PROGRESS_EVERY == 0 or index == total:
                self._progress(f"details {index}/{total} (ok={stats.ok}, missing={stats.missing})")
        return stats

    def _check_markup(self, stats: DetailStats) -> None:
        if stats.ok < MIN_SAMPLE_FOR_MARKUP_CHECK:
            return
        if stats.empty_description / stats.ok > MAX_EMPTY_DESCRIPTION_RATIO:
            raise MarkupChangedError(
                f"{stats.empty_description} of {stats.ok} detail pages had no description; "
                "LinkedIn markup may have changed"
            )
