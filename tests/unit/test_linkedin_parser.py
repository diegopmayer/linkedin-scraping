from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from jobscan.adapters import linkedin
from jobscan.domain.models import SliceSpec
from tests.conftest import FIXTURES, detail_page


def test_parse_count_exact_real_page() -> None:
    count = linkedin.parse_count((FIXTURES / "count_exact.html").read_text(encoding="utf-8"))
    assert count is not None
    assert (count.raw, count.value, count.is_lower_bound) == ("797", 797, False)


def test_parse_count_lower_bound_real_page() -> None:
    count = linkedin.parse_count((FIXTURES / "count_lower_bound.html").read_text(encoding="utf-8"))
    assert count is not None
    assert count.raw == "4,000+"
    assert count.value == 4000
    assert count.is_lower_bound is True


def test_parse_count_missing_banner() -> None:
    assert linkedin.parse_count("<html><body>nothing</body></html>") is None


def test_parse_cards_real_page() -> None:
    cards = linkedin.parse_cards((FIXTURES / "list_page.html").read_text(encoding="utf-8"))
    assert len(cards) == 10
    first = cards[0]
    assert first.job_id == "4481843507"
    assert first.title == "Data Engineer - Mid Level"
    assert first.company == "USAA"
    assert first.location_text == "Phoenix, AZ"
    assert first.posted_at == "2026-10-27"
    assert first.url.startswith("https://www.linkedin.com/jobs/view/")
    assert "?" not in first.url
    assert len({c.job_id for c in cards}) == 10


def test_parse_cards_empty_page_past_cap() -> None:
    assert linkedin.parse_cards((FIXTURES / "list_past_cap.html").read_text(encoding="utf-8")) == []


def test_parse_cards_skips_malformed() -> None:
    html = '<div class="base-card" data-entity-urn="urn:li:jobPosting:abc"><h3 class="base-search-card__title">X</h3>'
    assert linkedin.parse_cards(html) == []


def test_parse_detail_real_page_not_applicable_seniority() -> None:
    detail = linkedin.parse_detail("4481843507", (FIXTURES / "detail_open.html").read_text(encoding="utf-8"))
    assert detail.title == "Data Engineer - Mid Level"
    assert detail.seniority == "Not Applicable"
    assert detail.employment_type == "Full-time"
    assert detail.industries == "Financial Services"
    assert detail.applicants_text == "86 applicants"
    assert detail.is_closed is False
    assert len(detail.description_text) > 1000
    assert "visa sponsorship" in detail.description_text


def test_closed_detail() -> None:
    detail = linkedin.parse_detail("1", detail_page("Data Engineer", "<p>Build pipelines.</p>", closed=True))
    assert detail.is_closed is True
    assert detail.description_text == "Build pipelines."


def test_detail_without_description() -> None:
    detail = linkedin.parse_detail("1", "<html><body><h2 class='top-card-layout__title'>T</h2></body></html>")
    assert detail.description_text == ""
    assert detail.seniority is None


def test_urls_carry_remote_filter_and_slice_filters() -> None:
    spec = SliceSpec("data_engineer", "United States", "data engineer", "United States", "r2592000",
                     f_e="4", f_jt="F", sort_by="DD")
    query = parse_qs(urlparse(linkedin.list_url(spec, 990)).query)
    assert query["f_WT"] == ["2"]
    assert query["f_E"] == ["4"]
    assert query["f_JT"] == ["F"]
    assert query["sortBy"] == ["DD"]
    assert query["start"] == ["990"]
    assert linkedin.detail_url("42").endswith("/jobs-guest/jobs/api/jobPosting/42")


@pytest.mark.live
def test_live_smoke_markup_unchanged(settings) -> None:
    import httpx

    spec = SliceSpec("data_engineer", "Canada", "data engineer", "Canada", "r604800")
    headers = {"User-Agent": settings.app.http.user_agent, "Accept-Language": "en-US,en;q=0.9"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        count = linkedin.parse_count(client.get(linkedin.count_url(spec)).text)
        cards = linkedin.parse_cards(client.get(linkedin.list_url(spec, 0)).text)
        assert count is not None and count.value
        assert cards, "no job cards parsed from the live list page"
        detail = linkedin.parse_detail(cards[0].job_id, client.get(linkedin.detail_url(cards[0].job_id)).text)
    assert detail.description_text, "no description parsed from the live detail page"
    assert detail.title
