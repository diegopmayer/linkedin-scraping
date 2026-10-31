from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from jobscan.adapters import linkedin
from jobscan.adapters.store import DuckDbStore
from jobscan.application.ports import Fetcher
from jobscan.config import Settings
from jobscan.domain.models import DisplayedCount, SliceSpec
from jobscan.domain.roles import RoleMatcher
from jobscan.domain.slicing import needs_split, plan_children

logger = logging.getLogger(__name__)
END_OF_RESULTS_STATUSES = frozenset({400, 404})


@dataclass(frozen=True)
class SearchCount:
    role: str
    country: str
    keywords: str
    count: DisplayedCount | None


def search_id(run_id: str, spec: SliceSpec) -> str:
    raw = f"{run_id}|{spec.role}|{spec.country}|{spec.keywords}|{spec.time_window}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def root_specs(settings: Settings, *, roles: set[str] | None, countries: set[str] | None) -> list[SliceSpec]:
    specs: list[SliceSpec] = []
    for role_id, role in settings.app.roles.items():
        if roles and role_id not in roles:
            continue
        for country in settings.app.countries:
            if countries and country.name not in countries:
                continue
            for keyword in role.keywords:
                specs.append(SliceSpec(role_id, country.name, keyword, country.location, settings.app.time_window))
    return specs


class Collector:
    def __init__(
        self,
        settings: Settings,
        store: DuckDbStore,
        fetcher: Fetcher,
        run_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._fetcher = fetcher
        self._run_id = run_id
        self._matcher = RoleMatcher(settings.app.roles)
        self._progress = progress or (lambda message: None)
        self.pages_fetched = 0

    def fetch_count(self, spec: SliceSpec) -> DisplayedCount | None:
        result = self._fetcher.get(linkedin.count_url(spec), cache_scope="run")
        if result.status != 200:
            logger.warning("count page status %s for %s", result.status, spec.filters())
            return None
        return linkedin.parse_count(result.body)

    def count_only(self, specs: list[SliceSpec]) -> list[SearchCount]:
        counts: list[SearchCount] = []
        for spec in specs:
            count = self.fetch_count(spec)
            self._store.upsert_search(search_id(self._run_id, spec), self._run_id, spec, count)
            counts.append(SearchCount(spec.role, spec.country, spec.keywords, count))
        return counts

    def collect(self, specs: list[SliceSpec]) -> None:
        for root in specs:
            sid = search_id(self._run_id, root)
            stack: list[tuple[SliceSpec, str | None]] = [(root, None)]
            while stack:
                spec, parent_id = stack.pop()
                count = self.fetch_count(spec)
                if spec.depth == 0:
                    self._store.upsert_search(sid, self._run_id, spec, count)
                slice_id = spec.slice_id(self._run_id)
                self._store.upsert_slice(slice_id, sid, parent_id, spec, count)
                if count is not None and count.value == 0 and not count.is_lower_bound:
                    self._store.finish_slice(slice_id, pages=0, cards=0, hit_cap=False)
                    continue
                pages, cards_seen, reached_cap = self._paginate(spec, slice_id)
                split = needs_split(count, cap=self._settings.app.slicing.cap)
                if count is None and cards_seen == 0:
                    split = False
                children = plan_children(spec, dual_sort=self._settings.app.slicing.dual_sort_on_capped_leaf)
                self._store.finish_slice(slice_id, pages=pages, cards=cards_seen,
                                         hit_cap=split and reached_cap and not children)
                if split and reached_cap:
                    stack.extend((child, slice_id) for child in reversed(children))

    def _paginate(self, spec: SliceSpec, slice_id: str) -> tuple[int, int, bool]:
        pages = 0
        cards_seen = 0
        reached_cap = False
        cap = self._settings.app.slicing.cap
        for start in range(0, cap, linkedin.PAGE_SIZE):
            result = self._fetcher.get(linkedin.list_url(spec, start), cache_scope="run")
            self.pages_fetched += 0 if result.from_cache else 1
            if result.status in END_OF_RESULTS_STATUSES or result.status != 200:
                break
            cards = linkedin.parse_cards(result.body)
            if not cards:
                break
            pages += 1
            self._store.upsert_cards(cards, slice_id=slice_id, run_id=self._run_id)
            for card in cards:
                self._store.set_job_roles(card.job_id, self._matcher.match(card.title))
                near = self._matcher.boundary_roles(card.title)
                if near:
                    self._store.add_boundary_title(self._run_id, card.job_id, card.title, near)
            cards_seen += len(cards)
            if start + linkedin.PAGE_SIZE >= cap:
                reached_cap = True
            if len(cards) < linkedin.PAGE_SIZE:
                break
        self._progress(f"slice {spec.role}/{spec.country} f_E={spec.f_e} f_JT={spec.f_jt} "
                       f"sort={spec.sort_by}: {cards_seen} cards")
        return pages, cards_seen, reached_cap
