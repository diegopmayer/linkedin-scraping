from __future__ import annotations

import duckdb
import pytest

from jobscan.adapters.store import DuckDbStore
from jobscan.domain.models import Classification, Eligibility, JobCard, Method, RemoteStatus, TechHit


def card(job_id: str, title: str = "Data Engineer") -> JobCard:
    return JobCard(job_id, title, "Acme", "United States", "2026-10-27", f"https://x/{job_id}")


def test_schema_is_idempotent(store: DuckDbStore) -> None:
    from jobscan.adapters.store import SCHEMA_SQL

    store.con.execute(SCHEMA_SQL)
    assert store.con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 1


def test_upsert_cards_is_idempotent_and_records_sightings(store: DuckDbStore) -> None:
    new = store.upsert_cards([card("1"), card("2")], slice_id="s1", run_id="r1")
    again = store.upsert_cards([card("1", "Senior Data Engineer")], slice_id="s2", run_id="r1")
    assert new == ["1", "2"]
    assert again == []
    assert store.con.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert store.con.execute("SELECT title FROM jobs WHERE job_id = '1'").fetchone()[0] == "Senior Data Engineer"
    assert store.con.execute("SELECT count(*) FROM job_sightings WHERE job_id = '1'").fetchone()[0] == 2


def test_check_constraint_blocks_unverified_latam(store: DuckDbStore) -> None:
    bad = Classification(Eligibility.LATAM_FRIENDLY, Method.RULES, "none", quotes_verified=True)
    with pytest.raises(duckdb.ConstraintException):
        store.put_classification(job_id="1", run_id="r1", remote=RemoteStatus.REMOTE, result=bad,
                                 rules_version="v", prompt_version=None, llm_model=None, reasoning=None)
    unverified = Classification(Eligibility.LATAM_FRIENDLY, Method.LLM, "none", quotes_verified=False)
    with pytest.raises(duckdb.ConstraintException):
        store.put_classification(job_id="1", run_id="r1", remote=RemoteStatus.REMOTE, result=unverified,
                                 rules_version="v", prompt_version="p", llm_model="m", reasoning=None)


def test_raw_cache_roundtrip(store: DuckDbStore) -> None:
    store.put_raw("https://x/a", 200, "héllo", scope="run", run_id="r1")
    assert store.get_raw("https://x/a", scope="run", run_id="r1").body == "héllo"
    assert store.get_raw("https://x/a", scope="run", run_id="r2") is None


def test_technology_sync_is_stable(store: DuckDbStore) -> None:
    first = store.sync_technologies([("Python", "Languages"), ("SQL", "Languages")])
    second = store.sync_technologies([("SQL", "Languages"), ("Python", "Languages"), ("dbt", "Orchestration")])
    assert first["Python"] == second["Python"]
    assert second["dbt"] == 3
    store.put_job_technologies("1", [TechHit("Python", "Languages", 3)], second)
    store.put_job_technologies("1", [TechHit("SQL", "Languages", 1)], second)
    rows = store.con.execute("SELECT tech_id, mention_count FROM job_technologies WHERE job_id = '1'").fetchall()
    assert rows == [(second["SQL"], 1)]


def test_llm_cache_roundtrip(store: DuckDbStore) -> None:
    store.put_llm_cache("k", '{"a": 1}', prompt_version="p", model="m", input_tokens=10, output_tokens=5,
                        cache_read_tokens=0)
    assert store.get_llm_cache("k") == '{"a": 1}'
    assert store.get_llm_cache("missing") is None


def test_export_csv(store: DuckDbStore, tmp_path) -> None:
    out = tmp_path / "x" / "a.csv"
    store.export_csv([{"a": 1, "b": "x,y"}], out)
    assert out.read_text(encoding="utf-8").splitlines() == ["a,b", '1,"x,y"']
