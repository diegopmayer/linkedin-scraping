from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

from jobscan.adapters.store import DuckDbStore
from jobscan.application.ports import FetchResult
from jobscan.config import HttpConfig
from jobscan.domain.errors import BlockedError

logger = logging.getLogger(__name__)
BLOCK_STATUSES = frozenset({429, 999})
TRANSPORT_ERROR = 0


class PoliteFetcher:
    def __init__(
        self,
        cfg: HttpConfig,
        store: DuckDbStore,
        run_id: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._run_id = run_id
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._client = client or httpx.Client(
            headers={"User-Agent": cfg.user_agent, "Accept-Language": "en-US,en;q=0.9"},
            timeout=cfg.timeout_seconds,
            follow_redirects=True,
        )
        self._consecutive_blocks = 0
        self.request_count = 0
        self.error_count = 0

    def close(self) -> None:
        self._client.close()

    def _is_retryable(self, status: int) -> bool:
        return status in BLOCK_STATUSES or status >= 500 or status == TRANSPORT_ERROR

    def get(self, url: str, *, cache_scope: str, force: bool = False) -> FetchResult:
        if not force:
            cached = self._store.get_raw(url, scope=cache_scope, run_id=self._run_id)
            if cached is not None:
                return FetchResult(url, cached.status, cached.body, from_cache=True)

        attempt = 0
        while True:
            self._sleep(self._rng.uniform(self._cfg.min_delay_seconds, self._cfg.max_delay_seconds))
            self.request_count += 1
            try:
                response = self._client.get(url)
                status, body = response.status_code, response.text
            except httpx.TransportError as exc:
                logger.warning("transport error on %s: %s", url, exc)
                status, body = TRANSPORT_ERROR, ""

            if not self._is_retryable(status):
                self._consecutive_blocks = 0
                self._store.put_raw(url, status, body, scope=cache_scope, run_id=self._run_id)
                return FetchResult(url, status, body)

            self._consecutive_blocks += 1
            self.error_count += 1
            if self._consecutive_blocks >= self._cfg.max_consecutive_blocks:
                raise BlockedError(url=url, status=status)
            wait = min(self._cfg.backoff_base_seconds * (2**attempt), self._cfg.backoff_max_seconds)
            logger.warning("status %s on %s; backing off %.0fs (attempt %d)", status, url, wait, attempt + 1)
            self._sleep(wait)
            attempt += 1
