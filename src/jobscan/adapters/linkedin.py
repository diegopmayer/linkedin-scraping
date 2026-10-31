from __future__ import annotations

import re
from urllib.parse import urlencode

from selectolax.lexbor import LexborHTMLParser, LexborNode

from jobscan.domain.models import DisplayedCount, JobCard, JobDetail, SliceSpec
from jobscan.domain.text import html_to_text

BASE = "https://www.linkedin.com"
PAGE_SIZE = 10
MAX_START = 990
REMOTE_WORKPLACE = "2"
CLOSED_MARKER = "no longer accepting applications"


def _params(spec: SliceSpec) -> dict[str, str]:
    params = {"keywords": spec.keywords, "location": spec.location, "f_WT": REMOTE_WORKPLACE, "f_TPR": spec.time_window}
    if spec.f_e:
        params["f_E"] = spec.f_e
    if spec.f_jt:
        params["f_JT"] = spec.f_jt
    if spec.sort_by:
        params["sortBy"] = spec.sort_by
    return params


def count_url(spec: SliceSpec) -> str:
    return f"{BASE}/jobs/search?{urlencode(_params(spec))}"


def list_url(spec: SliceSpec, start: int) -> str:
    return f"{BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search?{urlencode({**_params(spec), 'start': start})}"


def detail_url(job_id: str) -> str:
    return f"{BASE}/jobs-guest/jobs/api/jobPosting/{job_id}"


def _text(node: LexborNode | None) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip()


def parse_count(html: str) -> DisplayedCount | None:
    node = LexborHTMLParser(html).css_first(".results-context-header__job-count")
    if node is None:
        return None
    raw = _text(node)
    digits = re.sub(r"[^\d]", "", raw)
    return DisplayedCount(raw=raw, value=int(digits) if digits else None, is_lower_bound=raw.endswith("+"))


def parse_cards(html: str) -> list[JobCard]:
    cards: list[JobCard] = []
    for card in LexborHTMLParser(html).css("div.base-card[data-entity-urn]"):
        urn = card.attributes.get("data-entity-urn") or ""
        job_id = urn.rsplit(":", 1)[-1]
        title = _text(card.css_first(".base-search-card__title"))
        if not job_id.isdigit() or not title:
            continue
        link = card.css_first("a.base-card__full-link")
        company_link = card.css_first(".base-search-card__subtitle a")
        posted = card.css_first("time")
        href = (link.attributes.get("href") or "") if link is not None else ""
        company_href = (company_link.attributes.get("href") or "") if company_link is not None else ""
        cards.append(
            JobCard(
                job_id=job_id,
                title=title,
                company=_text(card.css_first(".base-search-card__subtitle")),
                location_text=_text(card.css_first(".job-search-card__location")),
                posted_at=posted.attributes.get("datetime") if posted is not None else None,
                url=href.split("?")[0] or detail_url(job_id),
                company_url=company_href.split("?")[0] or None,
            )
        )
    return cards


def parse_detail(job_id: str, html: str) -> JobDetail:
    tree = LexborHTMLParser(html)
    description = tree.css_first(".show-more-less-html__markup")
    criteria: dict[str, str] = {}
    for item in tree.css(".description__job-criteria-item"):
        key = _text(item.css_first(".description__job-criteria-subheader"))
        value = _text(item.css_first(".description__job-criteria-text"))
        if key:
            criteria[key] = value
    page_text = _text(tree.body).lower() if tree.body is not None else ""
    description_html = (description.html or "") if description is not None else ""
    return JobDetail(
        job_id=job_id,
        title=_text(tree.css_first(".top-card-layout__title")),
        description_html=description_html,
        description_text=html_to_text(description_html),
        seniority=criteria.get("Seniority level"),
        employment_type=criteria.get("Employment type"),
        job_function=criteria.get("Job function"),
        industries=criteria.get("Industries"),
        applicants_text=_text(tree.css_first(".num-applicants__caption")) or None,
        is_closed=CLOSED_MARKER in page_text,
    )
