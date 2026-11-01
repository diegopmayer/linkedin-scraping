from __future__ import annotations

from datetime import date

from jobscan.domain.dedup import PostingCandidate, group_postings, posting_scope, shingles, similarity

BODY = (
    "We are hiring a Senior Data Engineer to build batch and streaming pipelines with Spark, Airflow and dbt on AWS. "
    "You will own data models, data quality checks and the on-call rotation for the warehouse. "
    "Requirements: five years of Python and SQL, experience with Snowflake or Redshift, and strong communication. "
    "Benefits include health insurance, a learning budget and flexible hours."
)


def job(job_id: str, *, company: str = "Capital One", title: str = "Data Engineer 4", body: str = BODY,
        posted: date | None = None) -> PostingCandidate:
    return PostingCandidate(job_id, company, title, body, posted)


def groups(mapping: dict[str, str]) -> set[frozenset[str]]:
    by_rep: dict[str, set[str]] = {}
    for job_id, rep in mapping.items():
        by_rep.setdefault(rep, set()).add(job_id)
    return {frozenset(members) for members in by_rep.values()}


def test_identical_copies_are_one_posting() -> None:
    mapping = group_postings([job("1"), job("2"), job("3")], min_similarity=0.9)
    assert groups(mapping) == {frozenset({"1", "2", "3"})}


def test_city_and_salary_line_differences_still_merge() -> None:
    long_body = BODY + " ".join(f" Duty {n}: maintain pipeline {n} and its tests for squad {n}." for n in range(30))
    a = long_body + " Location: McLean, VA. Salary range for McLean, VA: $150,000 - $170,000."
    b = long_body + " Location: Richmond, VA. Salary range for Richmond, VA: $140,000 - $160,000."
    assert similarity(shingles(a), shingles(b)) >= 0.9
    assert groups(group_postings([job("1", body=a), job("2", body=b)], min_similarity=0.9)) == {
        frozenset({"1", "2"})}


def test_same_title_different_job_stays_separate() -> None:
    other = ("Data Engineer for our retail client. Migrate legacy Informatica jobs to Azure Data Factory, "
             "write T-SQL stored procedures and support Power BI reports for the finance team.")
    mapping = group_postings([job("1", company="TCS", title="Data Engineer"),
                              job("2", company="TCS", title="Data Engineer", body=other)], min_similarity=0.9)
    assert groups(mapping) == {frozenset({"1"}), frozenset({"2"})}


def test_different_title_or_company_never_merges() -> None:
    mapping = group_postings([job("1"), job("2", title="Data Engineer 3"), job("3", company="Capital Two")],
                             min_similarity=0.9)
    assert len(groups(mapping)) == 3


def test_title_and_company_normalised() -> None:
    assert posting_scope("Capital One ", "Data Engineer 4 – Remote") == posting_scope(
        "capital one", "data engineer 4 - remote")
    mapping = group_postings([job("1", title="Sr. Data Engineer"), job("2", title="SR DATA ENGINEER")],
                             min_similarity=0.9)
    assert len(groups(mapping)) == 1


def test_chain_of_near_copies_is_one_group() -> None:
    words = BODY.split()
    v1 = " ".join(words)
    v2 = " ".join(words[:-2] + ["remote", "friendly"])
    v3 = " ".join(words[:-4] + ["remote", "friendly", "extra", "words"])
    mapping = group_postings([job("1", body=v1), job("2", body=v2), job("3", body=v3)], min_similarity=0.85)
    assert len(groups(mapping)) == 1


def test_representative_is_newest_then_smallest_id() -> None:
    mapping = group_postings([job("30", posted=date(2026, 10, 1)), job("12", posted=date(2026, 10, 20)),
                              job("9", posted=date(2026, 10, 20)), job("4")], min_similarity=0.9)
    assert set(mapping.values()) == {"9"}


def test_threshold_one_means_identical_text_only() -> None:
    mapping = group_postings([job("1"), job("2", body=BODY + " Apply today.")], min_similarity=1.0)
    assert len(groups(mapping)) == 2


def test_every_job_is_mapped() -> None:
    mapping = group_postings([job("1"), job("2", company="Other")], min_similarity=0.9)
    assert mapping == {"1": "1", "2": "2"}
