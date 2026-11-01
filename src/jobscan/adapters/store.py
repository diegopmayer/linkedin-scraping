from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

import duckdb

from jobscan.domain.dedup import PostingCandidate
from jobscan.domain.models import Classification, DisplayedCount, JobCard, JobDetail, RemoteStatus, SliceSpec, TechHit
from jobscan.domain.text import text_hash

SCHEMA_SQL = files("jobscan.adapters").joinpath("sql/schema.sql").read_text(encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class RawResponse:
    status: int
    body: str


@dataclass(frozen=True)
class JobToClassify:
    job_id: str
    title: str
    location_text: str
    description_text: str


class DuckDbStore:
    def __init__(self, database: str | Path) -> None:
        if str(database) != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(database))
        self.con.execute(SCHEMA_SQL)

    def close(self) -> None:
        self.con.close()

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self.con.execute(sql, list(params))
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def create_run(self, run_id: str, *, mode: str, config_hash: str, roles: str | None, countries: str | None) -> None:
        self.con.execute(
            "INSERT INTO runs (run_id, mode, started_at, status, stage, config_hash, roles_filter, countries_filter) "
            "VALUES (?, ?, ?, 'running', 'collect', ?, ?, ?)",
            [run_id, mode, _now(), config_hash, roles, countries],
        )

    def latest_resumable_run(self, mode: str = "run") -> dict[str, Any] | None:
        rows = self._rows(
            "SELECT * FROM runs WHERE mode = ? AND status IN ('running', 'paused', 'failed') "
            "ORDER BY started_at DESC LIMIT 1",
            [mode],
        )
        return rows[0] if rows else None

    def latest_run(self, mode: str = "run") -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM runs WHERE mode = ? ORDER BY started_at DESC LIMIT 1", [mode])
        return rows[0] if rows else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM runs WHERE run_id = ?", [run_id])
        return rows[0] if rows else None

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{name} = ?" for name in fields)
        self.con.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?", [*fields.values(), run_id])

    def add_run_counters(self, run_id: str, **increments: int) -> None:
        if not increments:
            return
        assignments = ", ".join(f"{name} = {name} + ?" for name in increments)
        self.con.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?", [*increments.values(), run_id])

    def get_raw(self, url: str, *, scope: str, run_id: str) -> RawResponse | None:
        if scope == "run":
            row = self.con.execute(
                "SELECT status, body_gz FROM raw_responses WHERE url = ? AND run_id = ? AND scope = 'run'",
                [url, run_id],
            ).fetchone()
        else:
            row = self.con.execute(
                "SELECT status, body_gz FROM raw_responses WHERE url = ? AND scope = 'global' "
                "ORDER BY fetched_at DESC LIMIT 1",
                [url],
            ).fetchone()
        if row is None:
            return None
        return RawResponse(int(row[0]), gzip.decompress(row[1]).decode("utf-8"))

    def put_raw(self, url: str, status: int, body: str, *, scope: str, run_id: str) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO raw_responses (url, scope, run_id, status, fetched_at, body_gz) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [url, scope, run_id, status, _now(), gzip.compress(body.encode("utf-8"))],
        )

    def upsert_search(
        self, search_id: str, run_id: str, spec: SliceSpec, count: DisplayedCount | None
    ) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO searches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                search_id, run_id, spec.role, spec.country, spec.keywords, spec.time_window,
                count.raw if count else None, count.value if count else None,
                count.is_lower_bound if count else None,
            ],
        )

    def upsert_slice(
        self, slice_id: str, search_id: str, parent_id: str | None, spec: SliceSpec, count: DisplayedCount | None
    ) -> None:
        exists = self.con.execute("SELECT 1 FROM slices WHERE slice_id = ?", [slice_id]).fetchone()
        if exists:
            return
        self.con.execute(
            "INSERT INTO slices (slice_id, search_id, parent_slice_id, depth, filters_json, displayed_count_raw, "
            "displayed_count, is_lower_bound) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                slice_id, search_id, parent_id, spec.depth, json.dumps(spec.filters(), sort_keys=True),
                count.raw if count else None, count.value if count else None, count.is_lower_bound if count else None,
            ],
        )

    def slice_done(self, slice_id: str) -> bool:
        row = self.con.execute("SELECT done FROM slices WHERE slice_id = ?", [slice_id]).fetchone()
        return bool(row and row[0])

    def finish_slice(self, slice_id: str, *, pages: int, cards: int, hit_cap: bool) -> None:
        self.con.execute(
            "UPDATE slices SET pages_fetched = ?, cards_seen = ?, hit_cap = ?, done = TRUE WHERE slice_id = ?",
            [pages, cards, hit_cap, slice_id],
        )

    def upsert_cards(self, cards: Iterable[JobCard], *, slice_id: str, run_id: str) -> list[str]:
        new_ids: list[str] = []
        for card in cards:
            existing = self.con.execute("SELECT 1 FROM jobs WHERE job_id = ?", [card.job_id]).fetchone()
            if existing:
                self.con.execute(
                    "UPDATE jobs SET title = ?, company = ?, location_text = ?, url = ?, last_seen_run = ? "
                    "WHERE job_id = ?",
                    [card.title, card.company, card.location_text, card.url, run_id, card.job_id],
                )
            else:
                new_ids.append(card.job_id)
                self.con.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, TRY_CAST(? AS DATE), ?, ?, ?)",
                    [
                        card.job_id, card.title, card.company, card.company_url, card.location_text,
                        card.posted_at, card.url, run_id, run_id,
                    ],
                )
            self.con.execute(
                "INSERT OR IGNORE INTO job_sightings VALUES (?, ?, ?)", [card.job_id, slice_id, run_id]
            )
        return new_ids

    def set_job_roles(self, job_id: str, roles: set[str]) -> None:
        self.con.execute("DELETE FROM job_roles WHERE job_id = ?", [job_id])
        for role in sorted(roles):
            self.con.execute("INSERT INTO job_roles VALUES (?, ?)", [job_id, role])

    def add_boundary_title(self, run_id: str, job_id: str, title: str, near_roles: set[str]) -> None:
        for role in sorted(near_roles):
            self.con.execute(
                "INSERT OR IGNORE INTO boundary_titles VALUES (?, ?, ?, ?)", [run_id, job_id, title, role]
            )

    def jobs_needing_details(self, run_id: str, *, refresh: bool, roles: set[str] | None = None) -> list[str]:
        role_filter = ""
        params: list[Any] = [run_id]
        if roles:
            role_filter = f" AND jr.role IN ({', '.join('?' for _ in roles)})"
            params.extend(sorted(roles))
        detail_filter = "" if refresh else " AND (d.job_id IS NULL OR (NOT d.fetched_ok AND d.http_status >= 500))"
        sql = (
            "SELECT DISTINCT js.job_id FROM job_sightings js "
            "JOIN job_roles jr ON jr.job_id = js.job_id "
            "LEFT JOIN job_details d ON d.job_id = js.job_id "
            f"WHERE js.run_id = ?{role_filter}{detail_filter} ORDER BY js.job_id"
        )
        return [row[0] for row in self.con.execute(sql, params).fetchall()]

    def put_detail(self, detail: JobDetail | None, *, job_id: str, http_status: int, html: str) -> None:
        if detail is None:
            self.con.execute(
                "INSERT OR REPLACE INTO job_details (job_id, fetched_at, fetched_ok, http_status, is_closed) "
                "VALUES (?, ?, FALSE, ?, FALSE)",
                [job_id, _now(), http_status],
            )
            return
        self.con.execute(
            "INSERT OR REPLACE INTO job_details VALUES (?, ?, TRUE, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                job_id, _now(), http_status, detail.description_text, gzip.compress(html.encode("utf-8")),
                detail.seniority, detail.employment_type, detail.job_function, detail.industries,
                detail.applicants_text, detail.is_closed, text_hash(detail.description_text),
            ],
        )

    def jobs_to_classify(self, run_id: str, *, roles: set[str] | None = None) -> list[JobToClassify]:
        role_filter = ""
        params: list[Any] = [run_id, run_id]
        if roles:
            role_filter = f" AND jr.role IN ({', '.join('?' for _ in roles)})"
            params.extend(sorted(roles))
        sql = (
            "SELECT DISTINCT j.job_id, j.title, coalesce(j.location_text, ''), d.description_text "
            "FROM job_sightings js JOIN jobs j ON j.job_id = js.job_id "
            "JOIN job_roles jr ON jr.job_id = js.job_id "
            "JOIN job_details d ON d.job_id = js.job_id AND d.fetched_ok "
            "LEFT JOIN classifications c ON c.job_id = js.job_id AND c.run_id = ? "
            f"WHERE js.run_id = ? AND c.job_id IS NULL{role_filter} ORDER BY j.job_id"
        )
        return [JobToClassify(*row) for row in self.con.execute(sql, params).fetchall()]

    def put_classification(
        self,
        *,
        job_id: str,
        run_id: str,
        remote: RemoteStatus,
        result: Classification,
        rules_version: str,
        prompt_version: str | None,
        llm_model: str | None,
        reasoning: str | None,
    ) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO classifications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                job_id, run_id, remote.value, result.label.value, result.method.value, result.confidence,
                result.restriction_type, json.dumps(result.matched_phrases), json.dumps(result.evidence,
                ensure_ascii=False), result.quotes_verified, rules_version, prompt_version, llm_model, reasoning,
            ],
        )

    def clear_classifications(self, run_id: str) -> int:
        count = self.con.execute("SELECT count(*) FROM classifications WHERE run_id = ?", [run_id]).fetchone()
        self.con.execute("DELETE FROM classifications WHERE run_id = ?", [run_id])
        return int(count[0]) if count else 0

    def get_llm_cache(self, cache_key: str) -> str | None:
        row = self.con.execute("SELECT response_json FROM llm_cache WHERE cache_key = ?", [cache_key]).fetchone()
        return str(row[0]) if row else None

    def put_llm_cache(
        self, cache_key: str, response_json: str, *, prompt_version: str, model: str,
        input_tokens: int | None, output_tokens: int | None, cache_read_tokens: int | None,
    ) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, response_json, prompt_version, model, input_tokens, "
            "output_tokens, cache_read_tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [cache_key, response_json, prompt_version, model, input_tokens, output_tokens, cache_read_tokens],
        )

    def sync_technologies(self, techs: Sequence[tuple[str, str]]) -> dict[str, int]:
        for canonical, category in techs:
            row = self.con.execute("SELECT tech_id FROM technologies WHERE canonical = ?", [canonical]).fetchone()
            if row is None:
                next_id = self.con.execute("SELECT coalesce(max(tech_id), 0) + 1 FROM technologies").fetchone()
                self.con.execute(
                    "INSERT INTO technologies VALUES (?, ?, ?)", [next_id[0] if next_id else 1, canonical, category]
                )
            else:
                self.con.execute("UPDATE technologies SET category = ? WHERE canonical = ?", [category, canonical])
        rows = self.con.execute("SELECT canonical, tech_id FROM technologies").fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    def put_job_technologies(self, job_id: str, hits: Sequence[TechHit], tech_ids: dict[str, int]) -> None:
        self.con.execute("DELETE FROM job_technologies WHERE job_id = ?", [job_id])
        for hit in hits:
            self.con.execute(
                "INSERT INTO job_technologies VALUES (?, ?, ?, NULL)",
                [job_id, tech_ids[hit.canonical], hit.mention_count],
            )

    def funnel(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM v_funnel WHERE run_id = ? ORDER BY role, country", [run_id])

    def overall_totals(self, run_id: str) -> dict[str, Any]:
        rows = self._rows(
            "SELECT count(DISTINCT js.job_id) AS collected, count(DISTINCT jr.job_id) AS role_matched, "
            "count(DISTINCT q.job_id) AS qualified, "
            "count(DISTINCT CASE WHEN q.eligibility_label = 'LATAM_FRIENDLY' THEN q.job_id END) AS latam_friendly, "
            "count(DISTINCT CASE WHEN q.eligibility_label = 'UNCLEAR' THEN q.job_id END) AS unclear, "
            "count(DISTINCT CASE WHEN q.eligibility_label = 'US_CA_ONLY' THEN q.job_id END) AS us_ca_only, "
            "count(DISTINCT q.posting_id) AS unique_postings, "
            "count(DISTINCT CASE WHEN q.posting_label = 'LATAM_FRIENDLY' THEN q.posting_id END) "
            "AS unique_latam_friendly, "
            "count(DISTINCT CASE WHEN q.posting_label = 'UNCLEAR' THEN q.posting_id END) AS unique_unclear, "
            "count(DISTINCT CASE WHEN q.posting_label = 'US_CA_ONLY' THEN q.posting_id END) AS unique_us_ca_only "
            "FROM job_sightings js LEFT JOIN job_roles jr ON jr.job_id = js.job_id "
            "LEFT JOIN v_qualified_postings q ON q.job_id = jr.job_id AND q.run_id = js.run_id WHERE js.run_id = ?",
            [run_id],
        )
        return rows[0]

    def detail_stats(self, run_id: str) -> dict[str, Any]:
        return self._rows(
            "SELECT count(DISTINCT jr.job_id) AS role_matched, "
            "count(DISTINCT CASE WHEN d.fetched_ok THEN jr.job_id END) AS fetched_ok, "
            "count(DISTINCT CASE WHEN d.is_closed THEN jr.job_id END) AS closed "
            "FROM job_sightings js JOIN job_roles jr ON jr.job_id = js.job_id "
            "LEFT JOIN job_details d ON d.job_id = js.job_id WHERE js.run_id = ?",
            [run_id],
        )[0]

    def remote_split(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT remote_status, count(*) AS jobs FROM classifications WHERE run_id = ? GROUP BY 1 ORDER BY 2 DESC",
            [run_id],
        )

    def method_split(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT eligibility_label, method, count(*) AS jobs FROM classifications WHERE run_id = ? "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            [run_id],
        )

    def capped_slices(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT s.role, s.country, sl.filters_json, sl.displayed_count_raw, sl.cards_seen "
            "FROM slices sl JOIN searches s ON s.search_id = sl.search_id "
            "WHERE s.run_id = ? AND sl.hit_cap ORDER BY s.role, s.country, sl.depth",
            [run_id],
        )

    def coverage(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT s.role, s.country, sl.filters_json, sl.displayed_count, count(DISTINCT js.job_id) AS collected, "
            "round(100.0 * count(DISTINCT js.job_id) / nullif(sl.displayed_count, 0), 1) AS coverage_pct "
            "FROM slices sl JOIN searches s ON s.search_id = sl.search_id "
            "LEFT JOIN job_sightings js ON js.slice_id = sl.slice_id "
            "WHERE s.run_id = ? AND NOT coalesce(sl.is_lower_bound, TRUE) AND sl.displayed_count > 0 "
            "GROUP BY s.role, s.country, sl.filters_json, sl.displayed_count ORDER BY coverage_pct",
            [run_id],
        )

    def tech_ranking(self, run_id: str, *, by: str | None, limit: int) -> list[dict[str, Any]]:
        group_col = {"role": "jr.role", "label": "q.posting_label", "country": "s.country", None: "'all'"}[by]
        sql = f"""
            WITH base AS (
                SELECT DISTINCT {group_col} AS grp, q.posting_id, q.job_id
                FROM v_qualified_postings q
                JOIN job_roles jr ON jr.job_id = q.job_id
                JOIN job_sightings js ON js.job_id = q.job_id AND js.run_id = q.run_id
                JOIN slices sl ON sl.slice_id = js.slice_id
                JOIN searches s ON s.search_id = sl.search_id
                WHERE q.run_id = ?
            ), totals AS (SELECT grp, count(DISTINCT posting_id) AS jobs_in_group FROM base GROUP BY grp),
            ranked AS (
                SELECT b.grp, t.canonical, t.category, count(DISTINCT b.posting_id) AS jobs,
                       row_number() OVER (PARTITION BY b.grp
                                          ORDER BY count(DISTINCT b.posting_id) DESC, t.canonical) AS rk
                FROM base b JOIN job_technologies jt ON jt.job_id = b.job_id
                JOIN technologies t ON t.tech_id = jt.tech_id
                GROUP BY b.grp, t.canonical, t.category
            )
            SELECT r.grp AS "group", r.rk AS rank, r.canonical AS technology, r.category, r.jobs,
                   round(100.0 * r.jobs / tt.jobs_in_group, 1) AS pct_of_jobs
            FROM ranked r JOIN totals tt ON tt.grp = r.grp
            WHERE r.rk <= ? ORDER BY r.grp, r.rk
        """
        return self._rows(sql, [run_id, limit])

    def qualified_jobs(self, run_id: str, *, labels: Sequence[str] | None = None) -> list[dict[str, Any]]:
        label_filter = ""
        params: list[Any] = [run_id]
        if labels:
            label_filter = f" AND q.eligibility_label IN ({', '.join('?' for _ in labels)})"
            params.extend(labels)
        sql = (
            "SELECT q.job_id, j.title, j.company, j.location_text, j.posted_at, j.url, "
            "string_agg(DISTINCT jr.role, ', ' ORDER BY jr.role) AS roles, "
            "q.eligibility_label, q.method, q.confidence, q.restriction_type, q.remote_status, "
            "q.evidence_json, q.reasoning, d.seniority, d.employment_type, q.posting_id, q.copies "
            "FROM v_qualified_postings q JOIN jobs j ON j.job_id = q.job_id "
            "JOIN job_roles jr ON jr.job_id = q.job_id JOIN job_details d ON d.job_id = q.job_id "
            f"WHERE q.run_id = ?{label_filter} "
            "GROUP BY ALL ORDER BY q.eligibility_label, j.posted_at DESC NULLS LAST, j.company"
        )
        return self._rows(sql, params)

    def dedup_candidates(self, run_id: str) -> list[PostingCandidate]:
        rows = self.con.execute(
            "SELECT q.job_id, j.company, j.title, coalesce(d.description_text, ''), j.posted_at "
            "FROM v_qualified q JOIN jobs j ON j.job_id = q.job_id JOIN job_details d ON d.job_id = q.job_id "
            "WHERE q.run_id = ? ORDER BY q.job_id",
            [run_id],
        ).fetchall()
        return [PostingCandidate(str(r[0]), str(r[1]), str(r[2]), str(r[3]), r[4]) for r in rows]

    def put_postings(self, run_id: str, mapping: dict[str, str]) -> None:
        self.con.execute("DELETE FROM postings WHERE run_id = ?", [run_id])
        if mapping:
            self.con.executemany("INSERT INTO postings VALUES (?, ?, ?)",
                                 [[run_id, job_id, posting_id] for job_id, posting_id in mapping.items()])

    def qualified_postings(self, run_id: str) -> list[dict[str, Any]]:
        """One row per posting: its newest copy, the posting's label and where the copies are."""
        return self._rows(
            "WITH copies AS (SELECT q.posting_id, string_agg(DISTINCT j.location_text, '; ' "
            "ORDER BY j.location_text) AS locations FROM v_qualified_postings q JOIN jobs j ON j.job_id = q.job_id "
            "WHERE q.run_id = ? GROUP BY q.posting_id) "
            "SELECT q.job_id, j.title, j.company, j.location_text, j.posted_at, j.url, "
            "string_agg(DISTINCT jr.role, ', ' ORDER BY jr.role) AS roles, "
            "q.posting_label AS eligibility_label, q.method, q.confidence, q.restriction_type, q.remote_status, "
            "q.evidence_json, q.reasoning, d.seniority, d.employment_type, q.copies, c.locations "
            "FROM v_qualified_postings q JOIN jobs j ON j.job_id = q.job_id "
            "JOIN job_roles jr ON jr.job_id = q.job_id JOIN job_details d ON d.job_id = q.job_id "
            "JOIN copies c ON c.posting_id = q.posting_id "
            "WHERE q.run_id = ? AND q.job_id = q.posting_id "
            "GROUP BY ALL ORDER BY q.posting_label, j.posted_at DESC NULLS LAST, j.company",
            [run_id, run_id],
        )

    def largest_postings(self, run_id: str, *, limit: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT j.company, j.title, q.copies, q.posting_label AS eligibility_label "
            "FROM v_qualified_postings q JOIN jobs j ON j.job_id = q.job_id "
            "WHERE q.run_id = ? AND q.job_id = q.posting_id AND q.copies > 1 "
            "ORDER BY q.copies DESC, j.company, j.title LIMIT ?",
            [run_id, limit],
        )

    def audit_sample(self, run_id: str, *, per_label: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM (SELECT q.posting_label AS eligibility_label, q.method, q.confidence, j.title, j.company, "
            "j.url, q.evidence_json, "
            "row_number() OVER (PARTITION BY q.posting_label ORDER BY hash(q.job_id || ?)) AS rn "
            "FROM v_qualified_postings q JOIN jobs j ON j.job_id = q.job_id "
            "WHERE q.run_id = ? AND q.job_id = q.posting_id) WHERE rn <= ? "
            "ORDER BY eligibility_label, rn",
            [run_id, run_id, per_label],
        )

    def qualified_descriptions(self, run_id: str) -> list[str]:
        rows = self.con.execute(
            "SELECT d.description_text FROM v_qualified_postings q JOIN job_details d ON d.job_id = q.job_id "
            "WHERE q.run_id = ? AND q.job_id = q.posting_id",
            [run_id],
        ).fetchall()
        return [str(row[0] or "") for row in rows]

    def boundary_titles(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT near_role, title, count(*) AS jobs FROM boundary_titles WHERE run_id = ? "
            "GROUP BY near_role, title ORDER BY near_role, jobs DESC, title",
            [run_id],
        )

    def export_csv(self, rows: list[dict[str, Any]], path: Path) -> None:
        import csv

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            if not rows:
                handle.write("")
                return
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def quality_violations(self, run_id: str) -> dict[str, int]:
        checks = {
            "null_job_id": "SELECT count(*) FROM jobs WHERE job_id IS NULL",
            "unclassified_with_details": (
                "SELECT count(DISTINCT js.job_id) FROM job_sightings js JOIN job_roles jr ON jr.job_id = js.job_id "
                "JOIN job_details d ON d.job_id = js.job_id AND d.fetched_ok "
                "LEFT JOIN classifications c ON c.job_id = js.job_id AND c.run_id = js.run_id "
                "WHERE js.run_id = ? AND c.job_id IS NULL"
            ),
        }
        result: dict[str, int] = {}
        for name, sql in checks.items():
            row = self.con.execute(sql, [run_id] if "?" in sql else []).fetchone()
            result[name] = int(row[0]) if row else 0
        return result
