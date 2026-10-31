from __future__ import annotations

import pytest

from jobscan.config import Settings
from jobscan.domain.technologies import TechExtractor


@pytest.fixture(scope="module")
def extractor(base_settings: Settings) -> TechExtractor:
    return TechExtractor(base_settings.technologies.technologies)


def names(extractor: TechExtractor, text: str) -> set[str]:
    return {hit.canonical for hit in extractor.extract(text)}


def test_ambiguous_names(extractor: TechExtractor) -> None:
    found = names(extractor, "Our Go-to-market team will spark joy. Let's go!")
    assert "Go" not in found
    assert "Spark" not in found


def test_real_go_and_spark(extractor: TechExtractor) -> None:
    found = names(extractor, "Experience with Golang and PySpark on Databricks.")
    assert {"Go", "Spark", "Databricks"} <= found


def test_go_in_language_list(extractor: TechExtractor) -> None:
    assert "Go" in names(extractor, "Languages: Python, Go, Rust")


def test_r_only_in_language_context(extractor: TechExtractor) -> None:
    assert "R" in names(extractor, "Strong Python, R and SQL skills.")
    assert "R" not in names(extractor, "R&D team. Plan R.")


def test_counted_once_per_job_with_mention_count(extractor: TechExtractor) -> None:
    hits = {h.canonical: h for h in extractor.extract("Python " * 7 + "and SQL.")}
    assert hits["Python"].mention_count == 7
    assert hits["SQL"].mention_count == 1


@pytest.mark.parametrize(
    ("text", "tech", "expected"),
    [
        ("We use Java daily.", "Java", True),
        ("We use JavaScript daily.", "Java", False),
        ("Scala experience.", "Scala", True),
        ("Highly scalable systems.", "Scala", False),
        ("CI/CD with GitHub Actions.", "CI/CD", True),
        ("C# and .NET services.", "C#", True),
        ("Knowledge of C++.", "C++", True),
        ("NoSQL databases.", "SQL", False),
        ("Spark SQL jobs.", "SQL", True),
        ("Postgres and MySQL.", "PostgreSQL", True),
        ("AWS Lambda and S3.", "AWS Lambda", True),
        ("A lambda function in Python.", "AWS Lambda", False),
        ("Build RAG pipelines.", "RAG", True),
        ("Clean with a rag.", "RAG", False),
        ("Apache Iceberg tables.", "Iceberg", True),
        ("Tip of the iceberg.", "Iceberg", False),
    ],
)
def test_boundaries(extractor: TechExtractor, text: str, tech: str, expected: bool) -> None:
    assert (tech in names(extractor, text)) is expected


def test_list_has_enough_entries(base_settings: Settings) -> None:
    techs = base_settings.technologies.technologies
    assert len(techs) >= 70
    assert len({t.category for t in techs}) >= 12


def test_unknown_terms(extractor: TechExtractor) -> None:
    terms = extractor.unknown_terms("We use BigQuery, FooDB and SuperTool daily.")
    assert "FooDB" in terms
    assert "SuperTool" in terms
    assert "BigQuery" not in terms
