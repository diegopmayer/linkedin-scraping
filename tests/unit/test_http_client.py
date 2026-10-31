from __future__ import annotations

import random

import httpx
import pytest

from jobscan.adapters.http_client import PoliteFetcher
from jobscan.adapters.store import DuckDbStore
from jobscan.config import Settings
from jobscan.domain.errors import BlockedError


def make(settings: Settings, store: DuckDbStore, responses: list[int], *, delays=(2.0, 5.0)):
    http = settings.app.http.model_copy(update={
        "min_delay_seconds": delays[0], "max_delay_seconds": delays[1],
        "backoff_base_seconds": 30, "backoff_max_seconds": 600, "max_consecutive_blocks": 5,
    })
    calls: list[str] = []
    sleeps: list[float] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(queue.pop(0) if queue else 200, text="ok")

    fetcher = PoliteFetcher(http, store, "run1", client=httpx.Client(transport=httpx.MockTransport(handler)),
                            sleep=sleeps.append, rng=random.Random(7))
    return fetcher, calls, sleeps


def test_jittered_delay_before_each_request(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, sleeps = make(settings, store, [200, 200])
    fetcher.get("https://x/a", cache_scope="run")
    fetcher.get("https://x/b", cache_scope="run")
    assert len(calls) == 2
    assert len(sleeps) == 2
    assert all(2.0 <= s <= 5.0 for s in sleeps)


def test_backoff_schedule_then_success(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, sleeps = make(settings, store, [429, 999, 503, 200], delays=(0.0, 0.0))
    result = fetcher.get("https://x/a", cache_scope="run")
    assert result.status == 200
    assert len(calls) == 4
    assert [s for s in sleeps if s > 0] == [30, 60, 120]
    assert fetcher.error_count == 3


def test_backoff_is_capped(settings: Settings, store: DuckDbStore) -> None:
    http = settings.app.http.model_copy(update={"min_delay_seconds": 0, "max_delay_seconds": 0,
                                                "backoff_base_seconds": 400, "backoff_max_seconds": 600,
                                                "max_consecutive_blocks": 10})
    queue = [429, 429, 429, 200]
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(queue.pop(0), text="")))
    PoliteFetcher(http, store, "r", client=client, sleep=sleeps.append).get("https://x/a", cache_scope="run")
    assert [s for s in sleeps if s > 0] == [400, 600, 600]


def test_stops_after_consecutive_blocks(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, _ = make(settings, store, [999] * 10, delays=(0.0, 0.0))
    with pytest.raises(BlockedError) as info:
        fetcher.get("https://x/a", cache_scope="run")
    assert info.value.status == 999
    assert len(calls) == 5
    assert info.value.exit_code == 3


def test_400_returned_without_retry(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, _ = make(settings, store, [400], delays=(0.0, 0.0))
    assert fetcher.get("https://x/a?start=1000", cache_scope="run").status == 400
    assert len(calls) == 1


def test_run_cache_avoids_second_request(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, _ = make(settings, store, [200], delays=(0.0, 0.0))
    first = fetcher.get("https://x/a", cache_scope="run")
    second = fetcher.get("https://x/a", cache_scope="run")
    assert len(calls) == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.body == "ok"


def test_global_cache_shared_across_runs(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, _ = make(settings, store, [200], delays=(0.0, 0.0))
    fetcher.get("https://x/detail/1", cache_scope="global")
    other_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    other = PoliteFetcher(settings.app.http, store, "run2", client=other_client, sleep=lambda s: None)
    assert other.get("https://x/detail/1", cache_scope="global").from_cache is True
    assert other.request_count == 0


def test_force_bypasses_cache(settings: Settings, store: DuckDbStore) -> None:
    fetcher, calls, _ = make(settings, store, [200, 200], delays=(0.0, 0.0))
    fetcher.get("https://x/a", cache_scope="global")
    fetcher.get("https://x/a", cache_scope="global", force=True)
    assert len(calls) == 2
