from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jobscan.adapters.store import DuckDbStore
from jobscan.config import Settings
from jobscan.domain.dedup import group_postings
from jobscan.domain.technologies import TechExtractor

UNKNOWN_TERM_MIN_JOBS = 3
LARGEST_POSTINGS_SHOWN = 10
LABEL_TITLES = {
    "LATAM_FRIENDLY": "Can apply (LATAM-friendly)",
    "UNCLEAR": "Unclear (not stated)",
    "US_CA_ONLY": "US/Canada only",
}


def _evidence(value: Any) -> str:
    try:
        quotes = json.loads(value) if isinstance(value, str) else (value or [])
    except json.JSONDecodeError:
        return str(value)
    return " | ".join(str(q) for q in quotes)


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _md_table(rows: Sequence[dict[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    if not rows:
        return "_None._\n"
    header = "| " + " | ".join(title for _, title in columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(_md_cell(row.get(key)) for key, _ in columns) + " |" for row in rows]
    return "\n".join([header, divider, *body]) + "\n"


def _role_label(settings: Settings, role_id: str) -> str:
    role = settings.app.roles.get(role_id)
    return role.label if role else role_id


class ReportWriter:
    def __init__(self, settings: Settings, store: DuckDbStore) -> None:
        self._settings = settings
        self._store = store

    def write(self, run_id: str, *, include_unclear: bool) -> Path:
        out = self._settings.path(self._settings.app.paths.reports_dir) / run_id
        review = out / "review"
        run = self._store.get_run(run_id) or {}
        mapping = group_postings(self._store.dedup_candidates(run_id),
                                 min_similarity=self._settings.app.dedup.min_similarity)
        self._store.put_postings(run_id, mapping)
        funnel = self._store.funnel(run_id)
        for row in funnel:
            row["role"] = _role_label(self._settings, row["role"])
        totals = self._store.overall_totals(run_id)
        top_n = self._settings.app.report.top_technologies
        rankings = {
            "overall": self._store.tech_ranking(run_id, by=None, limit=top_n),
            "role": self._store.tech_ranking(run_id, by="role", limit=top_n),
            "label": self._store.tech_ranking(run_id, by="label", limit=top_n),
            "country": self._store.tech_ranking(run_id, by="country", limit=top_n),
        }
        all_jobs = self._store.qualified_jobs(run_id)
        postings = self._store.qualified_postings(run_id)
        for job in (*all_jobs, *postings):
            job["evidence"] = _evidence(job.pop("evidence_json"))
        can_apply = [job for job in postings if job["eligibility_label"] == "LATAM_FRIENDLY"]
        unclear = [job for job in postings if job["eligibility_label"] == "UNCLEAR"]
        audit = self._store.audit_sample(run_id, per_label=self._settings.app.report.audit_sample_per_label)
        for row in audit:
            row["evidence"] = _evidence(row.pop("evidence_json"))
            row.pop("rn", None)
        boundary = self._store.boundary_titles(run_id)
        unknown = self._unknown_terms(run_id)

        self._store.export_csv(funnel, out / "counts.csv")
        self._store.export_csv(can_apply, out / "can_apply.csv")
        self._store.export_csv(all_jobs, out / "jobs_all.csv")
        self._store.export_csv(
            [{"dimension": dim, **row} for dim, rows in rankings.items() for row in rows], out / "technologies.csv"
        )
        self._store.export_csv(audit, review / "audit_sample.csv")
        self._store.export_csv(boundary, review / "role_boundary.csv")
        self._store.export_csv(unknown, review / "unknown_terms.csv")

        markdown = self._markdown(run_id, run, funnel, totals, rankings, can_apply, unclear, audit,
                                  include_unclear=include_unclear)
        (out / "report.md").write_text(markdown, encoding="utf-8")
        return out

    def _unknown_terms(self, run_id: str) -> list[dict[str, Any]]:
        extractor = TechExtractor(self._settings.technologies.technologies)
        counter: Counter[str] = Counter()
        for text in self._store.qualified_descriptions(run_id):
            counter.update(extractor.unknown_terms(text))
        return [{"term": term, "jobs": n} for term, n in counter.most_common() if n >= UNKNOWN_TERM_MIN_JOBS]

    def _markdown(
        self,
        run_id: str,
        run: dict[str, Any],
        funnel: list[dict[str, Any]],
        totals: dict[str, Any],
        rankings: dict[str, list[dict[str, Any]]],
        can_apply: list[dict[str, Any]],
        unclear: list[dict[str, Any]],
        audit: list[dict[str, Any]],
        *,
        include_unclear: bool,
    ) -> str:
        details = self._store.detail_stats(run_id)
        largest = self._store.largest_postings(run_id, limit=LARGEST_POSTINGS_SHOWN)
        capped = self._store.capped_slices(run_id)
        low_coverage = [row for row in self._store.coverage(run_id) if (row["coverage_pct"] or 0) < 95]
        parts: list[str] = [
            f"# Remote job scan: {run_id}\n",
            f"- Status: **{run.get('status', '?')}** (stage `{run.get('stage', '?')}`)",
            f"- Started: {run.get('started_at')} UTC; finished: {run.get('finished_at') or '-'}",
            f"- Time window: `{self._settings.app.time_window}`; config hash `{run.get('config_hash')}`",
            f"- Requests: {run.get('request_count', 0)}; HTTP errors/retries: {run.get('error_count', 0)}",
            f"- LLM calls: {run.get('llm_calls', 0)} (input {run.get('llm_input_tokens', 0)}, output "
            f"{run.get('llm_output_tokens', 0)}, cache-read {run.get('llm_cache_read_tokens', 0)} tokens)",
            f"- Rules: `{self._settings.eligibility.rules_version}` + `{self._settings.remote.rules_version}`; "
            f"technologies `{self._settings.technologies.version}`",
        ]
        if run.get("message"):
            parts.append(f"- Note: {run['message']}")
        parts += [
            "\n## Counts\n",
            "Displayed = LinkedIn's banner (\"+\" means at least). Collected = unique jobs reached. "
            "Title-matched = title fits the role. Qualified = title-matched, remote (or unknown), open. "
            "Postings = qualified jobs with copies merged (same company, same title, near-identical "
            "description, e.g. one job posted once per city). The last three columns count postings; a "
            "posting takes the most restrictive label of its copies.\n",
            _md_table(funnel, [
                ("role", "Role"), ("country", "Country"), ("displayed_count_raw", "Displayed"),
                ("collected_count", "Collected"), ("role_matched_count", "Title-matched"),
                ("qualified_count", "Qualified"), ("unique_postings", "Postings"),
                ("unique_latam_friendly", "LATAM-friendly"), ("unique_unclear", "Unclear"),
                ("unique_us_ca_only", "US/CA-only"),
            ]),
            "\n**All roles, each job once:** "
            f"collected {totals['collected']}, title-matched {totals['role_matched']}, qualified {totals['qualified']}"
            f" → {totals['unique_postings']} postings: LATAM-friendly **{totals['unique_latam_friendly']}**, "
            f"unclear {totals['unique_unclear']}, US/CA-only {totals['unique_us_ca_only']}.\n",
            f"\nDetail pages: {details['fetched_ok']} of {details['role_matched']} title-matched jobs fetched; "
            f"{details['closed']} closed.\n",
        ]
        parts.append("\n### Coverage warnings\n")
        if not capped and not low_coverage:
            parts.append("No capped slices and no exact slice below 95% coverage.\n")
        if capped:
            parts.append("Slices that still hit LinkedIn's 1,000-result limit (some jobs were not reachable):\n")
            parts.append(_md_table(capped, [("role", "Role"), ("country", "Country"), ("filters_json", "Filters"),
                                            ("displayed_count_raw", "Displayed"), ("cards_seen", "Cards seen")]))
        if low_coverage:
            parts.append("\nExact slices below 95% coverage:\n")
            parts.append(_md_table(low_coverage, [("role", "Role"), ("country", "Country"),
                                                  ("filters_json", "Filters"), ("displayed_count", "Displayed"),
                                                  ("collected", "Collected"), ("coverage_pct", "Coverage %")]))

        parts.append("\n### Merged copies\n")
        if largest:
            parts.append("Postings with the most copies (each counted once above):\n")
            parts.append(_md_table(largest, [("company", "Company"), ("title", "Title"), ("copies", "Copies"),
                                             ("eligibility_label", "Label")]))
        else:
            parts.append("No duplicate postings found.\n")

        job_columns = [("title", "Title"), ("company", "Company"), ("roles", "Roles"), ("location_text", "Location"),
                       ("copies", "Copies"), ("posted_at", "Posted"), ("url", "Link"), ("evidence", "Evidence")]
        parts.append(f"\n## {LABEL_TITLES['LATAM_FRIENDLY']}: {len(can_apply)} postings\n")
        parts.append("Each posting's evidence is a sentence quoted from its description. Copies = how many times "
                     "it was posted (the link is the newest one; `can_apply.csv` lists every location).\n")
        parts.append(_md_table(can_apply, job_columns))
        if include_unclear:
            parts.append(f"\n## {LABEL_TITLES['UNCLEAR']}: {len(unclear)} postings\n")
            parts.append("These posts don't say who can be hired. They are NOT in the can-apply list.\n")
            parts.append(_md_table(unclear, job_columns[:-1]))
        else:
            parts.append(f"\n_{len(unclear)} unclear postings hidden; run `jobscan report --include-unclear` to "
                         "list them._\n")

        parts.append("\n## Technologies\n")
        parts.append("Share of qualified postings that mention each technology (copies of a posting counted "
                     "once).\n")
        parts.append("\n### Overall\n")
        parts.append(_md_table(rankings["overall"], [("rank", "#"), ("technology", "Technology"),
                                                     ("category", "Category"), ("jobs", "Postings"),
                                                     ("pct_of_jobs", "% of postings")]))
        for dimension, title in (("role", "By role"), ("label", "By eligibility"), ("country", "By country")):
            parts.append(f"\n### {title}\n")
            rows = rankings[dimension]
            for group in sorted({row["group"] for row in rows}):
                label = _role_label(self._settings, group) if dimension == "role" else group
                parts.append(f"\n**{label}**\n\n")
                parts.append(_md_table([r for r in rows if r["group"] == group][:15], [
                    ("rank", "#"), ("technology", "Technology"), ("jobs", "Postings"),
                    ("pct_of_jobs", "% of postings")]))

        parts.append("\n## Classification method\n")
        parts.append(_md_table(self._store.method_split(run_id), [("eligibility_label", "Label"),
                                                                  ("method", "Method"), ("jobs", "Jobs")]))
        parts.append("\nRemote check:\n\n")
        parts.append(_md_table(self._store.remote_split(run_id), [("remote_status", "Remote status"),
                                                                  ("jobs", "Jobs")]))
        parts.append("\n## Audit sample\n")
        parts.append("Random jobs per label to spot-check by hand (also in `review/audit_sample.csv`).\n")
        parts.append(_md_table(audit, [("eligibility_label", "Label"), ("method", "Method"),
                                       ("confidence", "Conf."), ("title", "Title"), ("company", "Company"),
                                       ("url", "Link"), ("evidence", "Evidence")]))
        parts.append("\n## Review files\n")
        parts.append("- `review/role_boundary.csv`: titles close to a role that were not counted\n")
        parts.append("- `review/unknown_terms.csv`: frequent tech-looking terms not in `config/technologies.yaml`\n")
        return "\n".join(parts)
