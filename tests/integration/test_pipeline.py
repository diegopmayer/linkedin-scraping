from __future__ import annotations

import csv
from pathlib import Path

import httpx
import pytest

from jobscan.adapters.store import DuckDbStore
from jobscan.config import Settings
from tests.conftest import FakeLlm, World, build_pipeline, detail_page, keyword_llm, list_page, make_settings

US_IDS = [str(i) for i in range(1, 41)]
CA_IDS = ["101", "102", "103"]
TITLES = {"5": "Software Engineer", "6": "Data Engineering Manager"}
DE_ONLY = {"data_engineer"}


def title(job_id: str) -> str:
    return TITLES.get(job_id, "Senior Data Engineer")


def description(job_id: str) -> str:
    kind = int(job_id) % 5
    return {
        0: "<p>Remote. Applicants must be authorized to work in the United States.</p>",
        1: ("<p>Fully remote. We hire contractors across Latin America via Deel.</p>"
            "<ul><li>Python</li><li>dbt</li></ul>"),
        2: "<p>Remote role building Spark pipelines with Python and dbt.</p>",
        3: "<p>This is a hybrid role: 3 days per week in our Austin office. We hire contractors via Deel.</p>",
        4: "<p>Remote. Open to residents of CA, NY, TX.</p>",
    }[kind]


def count_for(url: httpx.URL) -> str | None:
    params = url.params
    if params.get("location") == "Canada":
        return "3" if "f_E" not in params else "0"
    if "f_E" not in params:
        return "40+"
    return {"4": "12", "2": "4"}.get(params["f_E"], "0")


def cards_for(url: httpx.URL) -> list[tuple[str, str]]:
    params = url.params
    if params.get("location") == "Canada":
        ids = CA_IDS
    elif "f_E" not in params:
        ids = US_IDS
    elif params["f_E"] == "4":
        ids = [str(i) for i in range(25, 37)]
    elif params["f_E"] == "2":
        ids = [str(i) for i in range(37, 41)]
    else:
        ids = []
    return [(i, title(i)) for i in ids]


def detail_for(job_id: str) -> tuple[int, str]:
    if job_id == "8":
        return 404, ""
    return 200, detail_page(title(job_id), description(job_id), closed=job_id == "7")


def make_world(**kwargs: object) -> World:
    return World(count_for=count_for, cards_for=cards_for, detail_for=detail_for, **kwargs)


@pytest.fixture
def small_settings(base_settings: Settings, tmp_path: Path) -> Settings:
    return make_settings(base_settings, tmp_path, cap=30, split_by_facets=True)


@pytest.fixture
def small_store(small_settings: Settings) -> DuckDbStore:
    db = DuckDbStore(small_settings.path(small_settings.app.paths.database))
    yield db
    db.close()


def run_once(settings: Settings, store: DuckDbStore, world: World, llm: FakeLlm | None, **kwargs: object):
    options = {"resume": False, "refresh": False, "roles": DE_ONLY, "countries": None, "include_unclear": False}
    options.update(kwargs)
    return build_pipeline(settings, store, world, llm).run(**options)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def expected_latam() -> set[str]:
    return {i for i in US_IDS + CA_IDS if int(i) % 5 == 1 and title(i) == "Senior Data Engineer"}


def test_full_run_happy_path(small_settings: Settings, small_store: DuckDbStore) -> None:
    llm = FakeLlm(keyword_llm)
    outcome = run_once(small_settings, small_store, make_world(), llm)

    assert outcome.exit_code == 0
    assert outcome.status == "completed"
    out = outcome.report_dir
    assert out is not None
    for name in ("report.md", "can_apply.csv", "jobs_all.csv", "counts.csv", "technologies.csv",
                 "review/audit_sample.csv", "review/role_boundary.csv", "review/unknown_terms.csv"):
        assert (out / name).exists(), name

    can_apply = read_csv(out / "can_apply.csv")
    assert {row["job_id"] for row in can_apply} == expected_latam()
    assert all(row["eligibility_label"] == "LATAM_FRIENDLY" for row in can_apply)
    assert all("Deel" in row["evidence"] for row in can_apply)

    all_jobs = {row["job_id"]: row for row in read_csv(out / "jobs_all.csv")}
    assert all_jobs["10"]["eligibility_label"] == "US_CA_ONLY"
    assert all_jobs["10"]["method"] == "rules"
    assert all_jobs["4"]["eligibility_label"] == "US_CA_ONLY"
    assert all_jobs["4"]["method"] == "llm"
    assert all_jobs["2"]["eligibility_label"] == "UNCLEAR"
    assert "3" not in all_jobs
    assert "7" not in all_jobs
    assert "8" not in all_jobs
    assert "5" not in all_jobs and "6" not in all_jobs


def test_counts_funnel(small_settings: Settings, small_store: DuckDbStore) -> None:
    outcome = run_once(small_settings, small_store, make_world(), FakeLlm(keyword_llm))
    rows = {row["country"]: row for row in read_csv(outcome.report_dir / "counts.csv")}
    us = rows["United States"]
    assert us["displayed_count_raw"] == "40+"
    assert us["is_lower_bound"] == "True"
    assert int(us["collected_count"]) == 40
    assert int(us["role_matched_count"]) == 38
    hybrid = {i for i in US_IDS if int(i) % 5 == 3 and title(i) == "Senior Data Engineer"}
    expected_qualified = 38 - len(hybrid | {"7", "8"})
    assert int(us["qualified_count"]) == expected_qualified
    assert int(us["latam_friendly"]) + int(us["unclear"]) + int(us["us_ca_only"]) == expected_qualified
    ca = rows["Canada"]
    assert (ca["displayed_count_raw"], ca["collected_count"], ca["latam_friendly"]) == ("3", "3", "1")


def test_dedup_across_slices(small_settings: Settings, small_store: DuckDbStore) -> None:
    run_once(small_settings, small_store, make_world(), FakeLlm(keyword_llm))
    con = small_store.con
    assert con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 43
    assert con.execute("SELECT count(*) FROM jobs WHERE job_id = '27'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM job_sightings WHERE job_id = '27'").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM slices WHERE hit_cap").fetchone()[0] == 0


def test_capped_slice_is_split_and_reported(base_settings: Settings, tmp_path: Path) -> None:
    settings = make_settings(base_settings, tmp_path, cap=20, split_by_facets=True)
    store = DuckDbStore(settings.path(settings.app.paths.database))
    world = World(count_for=lambda url: "50+", cards_for=lambda url: [(i, "Data Engineer") for i in US_IDS],
                  detail_for=detail_for)
    outcome = run_once(settings, store, world, FakeLlm(keyword_llm), countries={"United States"})
    depths = [row[0] for row in store.con.execute("SELECT DISTINCT depth FROM slices ORDER BY 1").fetchall()]
    assert depths == [0, 1, 2, 3]
    capped = store.capped_slices(outcome.run_id)
    assert capped and all('"sortBy"' in row["filters_json"] for row in capped)
    assert "still hit LinkedIn's 1,000-result limit" in (outcome.report_dir / "report.md").read_text()
    store.close()


def test_unclear_hidden_by_default_and_shown_on_request(small_settings: Settings, small_store: DuckDbStore) -> None:
    llm = FakeLlm(keyword_llm)
    outcome = run_once(small_settings, small_store, make_world(), llm)
    report = (outcome.report_dir / "report.md").read_text(encoding="utf-8")
    assert "unclear jobs hidden" in report
    assert "## Unclear" not in report
    pipeline = build_pipeline(small_settings, small_store, make_world(), llm)
    shown = (pipeline.report(outcome.run_id, include_unclear=True) / "report.md").read_text(encoding="utf-8")
    assert "## Unclear (not stated)" in shown
    can_apply_ids = {row["job_id"] for row in read_csv(outcome.report_dir / "can_apply.csv")}
    assert can_apply_ids == expected_latam()


def test_no_llm_run_never_latam(small_settings: Settings, small_store: DuckDbStore) -> None:
    outcome = run_once(small_settings, small_store, make_world(), None)
    assert outcome.exit_code == 0
    assert read_csv(outcome.report_dir / "can_apply.csv") == []
    methods = {row[0] for row in small_store.con.execute("SELECT DISTINCT method FROM classifications").fetchall()}
    assert methods == {"rules", "rules-fallback"}


def test_fake_quote_from_llm_is_downgraded(small_settings: Settings, small_store: DuckDbStore) -> None:
    world = World(count_for=lambda url: "1", cards_for=lambda url: [("900", "Data Engineer")],
                  detail_for=lambda job_id: (200, detail_page("Data Engineer", "<p>Remote. invented claim.</p>")))
    outcome = run_once(small_settings, small_store, world, FakeLlm(keyword_llm), countries={"United States"})
    rows = read_csv(outcome.report_dir / "jobs_all.csv")
    assert [r["eligibility_label"] for r in rows] == ["UNCLEAR"]


def test_block_pauses_run_and_resume_repeats_no_successful_request(
    small_settings: Settings, small_store: DuckDbStore
) -> None:
    first_world = make_world(block_detail_after=10)
    paused = run_once(small_settings, small_store, first_world, FakeLlm(keyword_llm))
    assert paused.exit_code == 3
    assert paused.status == "paused"
    run_row = small_store.get_run(paused.run_id)
    assert run_row["status"] == "paused"
    assert run_row["stage"] == "details"

    detail_calls = [u.rsplit("/", 1)[-1] for u in first_world.log if "/jobPosting/" in u]
    fetched_ok_first = set(detail_calls[:10])
    assert len(detail_calls) == 10 + small_settings.app.http.max_consecutive_blocks

    second_world = make_world()
    resumed = run_once(small_settings, small_store, second_world, FakeLlm(keyword_llm), resume=True)
    assert resumed.exit_code == 0
    assert resumed.run_id == paused.run_id
    assert not [u for u in second_world.log if "seeMoreJobPostings" in u or "/jobs/search" in u]
    second_details = {u.rsplit("/", 1)[-1] for u in second_world.log if "/jobPosting/" in u}
    assert not (second_details & fetched_ok_first)
    assert len(second_details) == len(set(second_details))


def test_second_run_reuses_details_and_llm_cache(small_settings: Settings, small_store: DuckDbStore) -> None:
    run_once(small_settings, small_store, make_world(), FakeLlm(keyword_llm))
    world = make_world()
    second = run_once(small_settings, small_store, world, FakeLlm(keyword_llm))
    assert second.exit_code == 0
    assert not [u for u in world.log if "/jobPosting/" in u and not u.endswith("/8")]


def test_count_only_writes_six_rows(settings: Settings, store: DuckDbStore) -> None:
    world = World(count_for=lambda url: "10,000+" if url.params["location"] == "United States" else "797",
                  cards_for=lambda url: [], detail_for=lambda job_id: (404, ""))
    run_id, counts, out = build_pipeline(settings, store, world, None).count(roles=None, countries=None)
    rows = read_csv(out / "counts.csv")
    assert len(rows) == 6
    us = [r for r in rows if r["country"] == "United States"]
    assert all(r["displayed_count_raw"] == "10,000+" and r["is_lower_bound"] == "True" for r in us)
    assert all(r["displayed_count"] == "797" for r in rows if r["country"] == "Canada")
    assert len([u for u in world.log if "/jobs/search" in u]) == 6


class ShortPageWorld(World):
    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/seeMoreJobPostings/search"):
            self.log.append(str(request.url))
            start = int(request.url.params.get("start", "0"))
            pages = {0: [str(i) for i in range(500, 510)], 10: [str(i) for i in range(510, 519)],
                     20: [str(i) for i in range(519, 529)]}
            return httpx.Response(200, text=list_page([(i, "Data Engineer") for i in pages.get(start, [])]))
        return super().handler(request)


def test_short_page_mid_results_does_not_stop_pagination(small_settings: Settings, small_store: DuckDbStore) -> None:
    world = ShortPageWorld(count_for=lambda url: "29", cards_for=lambda url: [],
                           detail_for=lambda job_id: (200, detail_page("Data Engineer", "<p>Remote.</p>")))
    run_once(small_settings, small_store, world, None, countries={"United States"})
    assert small_store.con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 29


def test_split_when_count_says_more_even_if_root_ends_early(base_settings: Settings, tmp_path: Path) -> None:
    settings = make_settings(base_settings, tmp_path, cap=30, split_by_facets=True)
    store = DuckDbStore(settings.path(settings.app.paths.database))

    def counts(url: httpx.URL) -> str:
        if "f_E" not in url.params:
            return "7,000+"
        return "10" if url.params["f_E"] == "4" else "0"

    def cards(url: httpx.URL) -> list[tuple[str, str]]:
        if "f_E" not in url.params:
            return [(str(i), "Data Engineer") for i in range(1, 16)]
        return [(str(i), "Data Engineer") for i in range(200, 210)]

    world = World(count_for=counts, cards_for=cards, detail_for=detail_for)
    run_once(settings, store, world, None, countries={"United States"})
    assert store.con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 25
    assert store.con.execute("SELECT count(*) FROM slices WHERE depth = 1").fetchone()[0] == 6
    store.close()


def test_no_facet_split_by_default_marks_capped_root(base_settings: Settings, tmp_path: Path) -> None:
    settings = make_settings(base_settings, tmp_path, cap=20)
    store = DuckDbStore(settings.path(settings.app.paths.database))
    world = World(count_for=lambda url: "7,000+", cards_for=lambda url: [(i, "Data Engineer") for i in US_IDS],
                  detail_for=detail_for)
    outcome = run_once(settings, store, world, None, countries={"United States"})
    assert store.con.execute("SELECT max(depth), count(*) FROM slices").fetchone() == (0, 1)
    assert store.con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 20
    assert len(store.capped_slices(outcome.run_id)) == 1
    assert not [u for u in world.log if "f_E=" in u]
    store.close()
