from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from jobscan.adapters.http_client import PoliteFetcher
from jobscan.adapters.store import DuckDbStore
from jobscan.application.pipeline import Pipeline
from jobscan.config import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "linkedin"


def count_page(raw: str) -> str:
    return f'<html><body><h1><span class="results-context-header__job-count">{raw}</span> jobs</h1></body></html>'


def card_html(job_id: str, title: str, *, location: str = "United States", company: str | None = None) -> str:
    return (
        f'<li><div class="base-card relative" data-entity-urn="urn:li:jobPosting:{job_id}">'
        f'<a class="base-card__full-link absolute" href="https://www.linkedin.com/jobs/view/job-{job_id}?trk=x"></a>'
        f'<div class="base-search-card__info"><h3 class="base-search-card__title">\n  {title}\n</h3>'
        f'<h4 class="base-search-card__subtitle"><a class="hidden-nested-link" '
        f'href="https://www.linkedin.com/company/acme-{job_id}?trk=y">{company or f"Acme {job_id}"}</a></h4>'
        f'<span class="job-search-card__location">{location}</span>'
        f'<time class="job-search-card__listdate" datetime="2026-10-27">3 days ago</time></div></div></li>'
    )


def list_page(cards: list[tuple[str, str]], company_for: Callable[[str], str | None] | None = None) -> str:
    return "".join(card_html(job_id, title, company=company_for(job_id) if company_for else None)
                   for job_id, title in cards)


def detail_page(title: str, description_html: str, *, closed: bool = False, seniority: str = "Mid-Senior level") -> str:
    closed_html = '<figure class="closed-job"><figcaption>No longer accepting applications</figcaption></figure>'
    return (
        f'<html><body><section class="top-card-layout"><h2 class="top-card-layout__title">{title}</h2>'
        f'<span class="num-applicants__caption">42 applicants</span>{closed_html if closed else ""}</section>'
        f'<div class="show-more-less-html__markup">{description_html}</div>'
        '<ul class="description__job-criteria-list">'
        f'<li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Seniority level'
        f'</h3><span class="description__job-criteria-text">{seniority}</span></li>'
        '<li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Employment type'
        '</h3><span class="description__job-criteria-text">Full-time</span></li></ul></body></html>'
    )


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    return load_settings(ROOT / "config" / "searches.yaml")


def make_settings(base: Settings, tmp_path: Path, **slicing: object) -> Settings:
    app = base.app
    http = app.http.model_copy(update={"min_delay_seconds": 0, "max_delay_seconds": 0,
                                       "backoff_base_seconds": 0, "backoff_max_seconds": 0})
    paths = app.paths.model_copy(update={"database": str(tmp_path / "jobscan.duckdb"),
                                         "reports_dir": str(tmp_path / "reports"),
                                         "logs_dir": str(tmp_path / "logs")})
    sl = app.slicing.model_copy(update=slicing) if slicing else app.slicing
    return base.model_copy(update={"app": app.model_copy(update={"http": http, "paths": paths, "slicing": sl})})


@pytest.fixture
def settings(base_settings: Settings, tmp_path: Path) -> Settings:
    return make_settings(base_settings, tmp_path)


@pytest.fixture
def store(settings: Settings) -> DuckDbStore:
    db = DuckDbStore(settings.path(settings.app.paths.database))
    yield db
    db.close()


@dataclass
class FakeVerdict:
    label: str
    confidence: float
    restriction_type: str
    work_arrangement: str
    evidence_quotes: list[str]
    reasoning_short: str = "fake"


@dataclass
class FakeLlm:
    responses: Callable[[str], FakeVerdict | None]
    model: str = "fake-model"
    prompt_version: str = "fake_v1"
    calls_made: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    available: bool = True
    disabled_reason: str | None = None
    seen: list[str] = field(default_factory=list)

    def classify(self, *, title: str, location: str, description: str, hints: list[str]) -> FakeVerdict | None:
        self.calls_made += 1
        self.seen.append(description)
        return self.responses(description)


def keyword_llm(description: str) -> FakeVerdict | None:
    if "via Deel" in description:
        quote = next(s.strip() for s in description.split(".") if "via Deel" in s) + "."
        return FakeVerdict("LATAM_FRIENDLY", 0.95, "none", "REMOTE", [quote])
    if "invented" in description:
        return FakeVerdict("LATAM_FRIENDLY", 0.95, "none", "REMOTE", ["We hire everywhere on Earth today."])
    if "residents of CA" in description:
        return FakeVerdict("US_CA_ONLY", 0.9, "location_list", "REMOTE", ["Open to residents of CA, NY, TX."])
    return FakeVerdict("UNCLEAR", 0.85, "none", "UNKNOWN", [])


@dataclass
class World:
    count_for: Callable[[httpx.URL], str | None]
    cards_for: Callable[[httpx.URL], list[tuple[str, str]]]
    detail_for: Callable[[str], tuple[int, str]]
    log: list[str] = field(default_factory=list)
    block_detail_after: int | None = None
    detail_requests: int = 0
    company_for: Callable[[str], str | None] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.log.append(str(url))
        path = url.path
        if path == "/jobs/search":
            raw = self.count_for(url)
            return httpx.Response(200, text=count_page(raw) if raw is not None else "<html></html>")
        if path.endswith("/seeMoreJobPostings/search"):
            start = int(url.params.get("start", "0"))
            if start >= 1000:
                return httpx.Response(400, text="")
            cards = self.cards_for(url)
            return httpx.Response(200, text=list_page(cards[start: start + 10], self.company_for))
        if "/jobPosting/" in path:
            self.detail_requests += 1
            if self.block_detail_after is not None and self.detail_requests > self.block_detail_after:
                return httpx.Response(999, text="blocked")
            status, body = self.detail_for(path.rsplit("/", 1)[-1])
            return httpx.Response(status, text=body)
        return httpx.Response(404, text="")


def build_pipeline(settings: Settings, store: DuckDbStore, world: World, llm: FakeLlm | None) -> Pipeline:
    def fetcher_factory(run_id: str) -> PoliteFetcher:
        client = httpx.Client(transport=httpx.MockTransport(world.handler))
        return PoliteFetcher(settings.app.http, store, run_id, client=client, sleep=lambda seconds: None)

    return Pipeline(settings, store, fetcher_factory=fetcher_factory, llm_factory=lambda: llm,
                    progress=lambda message: None)
