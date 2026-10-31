# BUILD REPORT: LinkedIn Remote Job Scanner

> Implementation report for LinkedIn Remote Job Scanner (`jobscan` CLI)

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | LINKEDIN_REMOTE_JOB_SCANNER |
| **Date** | 2026-10-31 |
| **Author** | build-agent |
| **DEFINE** | [DEFINE_LINKEDIN_REMOTE_JOB_SCANNER.md](../features/DEFINE_LINKEDIN_REMOTE_JOB_SCANNER.md) |
| **DESIGN** | [DESIGN_LINKEDIN_REMOTE_JOB_SCANNER.md](../features/DESIGN_LINKEDIN_REMOTE_JOB_SCANNER.md) |
| **Status** | Complete (with two open items for the owner, see Blockers) |

---

## Summary

| Metric | Value |
|--------|-------|
| **Tasks Completed** | 45/45 manifest files + 2 extra test files |
| **Files Created** | 50 source/config/test/doc files + 5 HTML fixtures |
| **Lines of Code** | ~4,900 (src ≈ 2,570 incl. SQL/prompt; tests ≈ 1,580; config ≈ 400; README 91) |
| **Build Time** | One session, 2026-10-31 |
| **Tests Passing** | 221/221 run (1 skipped by design, 2 deselected: `llm`, `live` markers) |
| **Agents Used** | 0 delegated; all files written directly following the assigned agents' KB domains (see Decision 1) |

---

## Task Execution with Agent Attribution

| # | Task | Agent | Status | Notes |
|---|------|-------|--------|-------|
| 1 | `pyproject.toml` | (direct; manifest @python-developer) | ✅ Complete | Console script, pytest markers, ruff/mypy config |
| 2 | `.gitignore` | (direct) | ✅ Complete | |
| 3 | `.env.example` | (direct) | ✅ Complete | |
| 4 | `config/searches.yaml` | (direct; @python-developer) | ✅ Complete | 3 roles, 2 countries, politeness, LLM, report |
| 5 | `config/technologies.yaml` | (direct; @python-developer) | ✅ Complete | 114 technologies, 13 categories |
| 6 | `config/eligibility_rules.yaml` | (direct; @ai-prompt-specialist) | ✅ Complete | 48 restrictive rules (EN/PT/ES), hints, negations |
| 7 | `config/remote_rules.yaml` | (direct; @python-developer) | ✅ Complete | |
| 8 | `src/jobscan/prompts/eligibility_v1.md` | (direct; @ai-prompt-specialist) | ✅ Complete | 9 few-shot examples, injection notice |
| 9 | `src/jobscan/__init__.py` | (direct) | ✅ Complete | |
| 10 | `src/jobscan/config.py` | (direct; @python-developer) | ✅ Complete | Pydantic models, regex validation, config hash |
| 11–18 | `domain/` models, errors, text, slicing, roles, remote, eligibility, technologies | (direct; @python-developer) | ✅ Complete | Pure functions, 98–100% coverage |
| 19 | `application/ports.py` | (direct; @python-developer) | ✅ Complete | Read-only Protocols |
| 20 | `adapters/sql/schema.sql` | (direct; @schema-designer) | ✅ Complete | CHECK constraint enforces the LATAM rule |
| 21–24 | `adapters/` store, http_client, linkedin, llm_classifier | (direct; @python-developer / @ai-prompt-specialist) | ✅ Complete | |
| 25–30 | `application/` collect, fetch_details, classify, report, pipeline; `cli.py` | (direct; @python-developer) | ✅ Complete | |
| 31–42 | `tests/conftest.py`, fixtures, unit and integration tests | (direct; @test-generator) | ✅ Complete | |
| 43–44 | `tests/golden/cases.yaml`, `test_golden.py` | (direct; @ai-prompt-specialist) | ✅ Complete | 32 synthetic cases; real cases still needed |
| 45 | `README.md` | (direct; @code-documenter) | ✅ Complete | |
| + | `tests/unit/test_llm_classifier.py`, `tests/unit/test_cli.py` | (direct; @test-generator) | ✅ Complete | Added to close coverage gaps (Decision 8) |

**Agent Key:** `(direct; @x)` = written by build-agent following the KB domains and patterns of the agent the manifest assigned.

---

## Agent Contributions

| Agent (as assigned in manifest) | Files | Specialization Applied |
|-------|-------|------------------------|
| @python-developer | 27 | `kb/python` clean-architecture (domain ← application ← adapters), error-handling hierarchy, dataclasses, type hints |
| @ai-prompt-specialist | 5 | `kb/pydantic/llm-output-validation`, `kb/prompt-engineering` structured extraction, `kb/genai/guardrails` (output validation, untrusted input wrapping) |
| @schema-designer | 1 | `kb/modern-stack/duckdb` views and constraints |
| @test-generator | 14 | `kb/testing` AAA unit tests, parametrize, fixtures, mocking (httpx `MockTransport`, fake LLM) |
| @code-documenter | 1 | User-facing README |
| (general) | 3 | Trivial files |

---

## Files Created

| File | Lines | Verified | Notes |
| ---- | ----- | -------- | ----- |
| `pyproject.toml` | 61 | ✅ | `pip install -e .` OK |
| `.gitignore`, `.env.example` | 12, 1 | ✅ | |
| `config/searches.yaml` | 103 | ✅ | Loads + validates |
| `config/technologies.yaml` | 168 | ✅ | 114 entries / 13 categories |
| `config/eligibility_rules.yaml` | 99 | ✅ | All regexes compile (validated on load) |
| `config/remote_rules.yaml` | 33 | ✅ | |
| `src/jobscan/prompts/eligibility_v1.md` | 91 | ✅ | Loaded via `importlib.resources` |
| `src/jobscan/config.py` | 194 | ✅ | |
| `src/jobscan/domain/*.py` (8 files) | 501 | ✅ | |
| `src/jobscan/adapters/*.py` + `sql/schema.sql` | 1,002 | ✅ | |
| `src/jobscan/application/*.py` (6 files) | 832 | ✅ | |
| `src/jobscan/cli.py` | 159 | ✅ | `jobscan --help`, real `jobscan count` run |
| `tests/conftest.py` | 158 | ✅ | |
| `tests/fixtures/linkedin/*.html` | 5 files | ✅ | Real pages saved 2026-10-31 (count exact, count "4,000+", list, detail, empty past-cap) |
| `tests/unit/*.py` (12 files) | 1,000 | ✅ | |
| `tests/integration/test_pipeline.py` | 235 | ✅ | |
| `tests/golden/cases.yaml`, `test_golden.py` | 197, 93 | ✅ | |
| `README.md` | 91 | ✅ | |

---

## Verification Results

### Lint Check

```text
$ ruff check src tests
All checks passed!
```

**Status:** ✅ Pass

### Type Check

```text
$ mypy
Success: no issues found in 26 source files
```

**Status:** ✅ Pass

### Tests

```text
$ pytest --cov=jobscan
221 passed, 1 skipped, 2 deselected in 45s
TOTAL coverage 92%  (domain 98–100%, adapters 85–100%, application 83–97%, cli 64%)

$ pytest -m live tests/unit/test_linkedin_parser.py
1 passed  (real count, list and detail pages parsed on 2026-10-31)

$ jobscan count        (real LinkedIn, 6 requests)
Data Engineer                United States   11,000+
Data Engineer                Canada          5,000+
Forward Deployed Engineer    United States   11,000+
Forward Deployed Engineer    Canada          7,000+
AI Engineer                  United States   11,000+
AI Engineer                  Canada          5,000+
```

| Test group | Result |
|------|--------|
| Parsers on real fixtures (`test_linkedin_parser`) | ✅ 10/10 + live smoke ✅ |
| Slicing, roles (24 titles), remote (10 cases), technologies (25 cases) | ✅ |
| Eligibility rules (21 clear restrictions incl. PT/ES, 5 negated/contextual, 6 no-restriction, stock text, real USAA post) | ✅ |
| Eligibility decision (quote verification, threshold, fallbacks) | ✅ |
| HTTP politeness (jitter, backoff 30→60→120, cap 600, stop after 5, cache, force) | ✅ |
| Store (idempotent upserts, CHECK constraint, caches, export) | ✅ |
| LLM adapter (request shape, cache, refusal, invalid JSON, auth disable, budget) | ✅ |
| CLI (help, errors, exit codes) | ✅ |
| Integration (10 end-to-end scenarios on a fake LinkedIn) | ✅ |
| Golden offline (rules decide exactly the 15 expected cases, never exclude the 17 others) | ✅ 47/47 |
| Golden with real LLM (`-m llm`) | ⏭️ Not run: no Anthropic credentials on this machine |
| Real golden cases ≥ 30 | ⏭️ Skipped (0 real cases yet) |

**Status:** ✅ 221/221 pass

---

## Issues Encountered

| # | Issue | Resolution | Time Impact |
|---|-------|------------|-------------|
| 1 | `selectolax` 1.0 removed the `selectolax.parser` (Modest) backend; import raised `ImportError` | Switched to `selectolax.lexbor.LexborHTMLParser` (same API); always use `text(separator=" ")` because `text(strip=True)` joins nested nodes without spaces | small |
| 2 | Installed `anthropic` is 2.3.0 (skill docs describe 1.x) | Inspected the installed SDK: `messages.create` accepts `output_config={effort, format}`, `system` blocks with `cache_control`; typed errors unchanged. Code matches the installed version | small |
| 3 | Tech context window crossed sentences ("spark joy." counted as Spark because "Python" was in the next sentence) | Context check limited to the same sentence | small |
| 4 | Portuguese visa rule missed "visto de trabalho nos EUA" | Rule widened (`(visto|autorização)( de trabalho)?`), test kept as written | small |
| 5 | Funnel view only counted a job under a role if that role's search found it (contradicted DESIGN Decision 5) | View rewritten: role matching uses every job seen in the country | small |
| 6 | `parse_detail` operator-precedence bug (`a.html or "" if … else ""`) | Parenthesised | small |
| 7 | `finish_slice` was given the global page counter | Per-slice page count | small |
| 8 | Protocol attributes vs Pydantic `Literal` fields failed mypy | Protocols use read-only properties | small |

---

## Autonomous Decisions

| # | Decision Point | Options Considered | Chose | Rationale |
|---|----------------|--------------------|-------|-----------|
| 1 | Delegate each file to the manifest's specialist agent via subagents, or write directly | Spawn 5 agent types for 45 tightly coupled files vs. one writer following each agent's KB domain | Write directly | Files share models, protocols and SQL; one writer keeps interfaces consistent and avoids re-deriving context 45 times. Agent KB patterns were still applied (attribution table) |
| 2 | Project virtual environment | System Python vs. `.venv` in project | `.venv` + `pip install -e ".[dev]"` | Isolated, reproducible; README documents it |
| 3 | HTML parser backend | Pin `selectolax<1.0` vs. Lexbor backend | Lexbor | Modest is deprecated and removed; Lexbor is maintained |
| 4 | JSON columns in DuckDB | `JSON` type (needs json extension, may download) vs. `VARCHAR` | `VARCHAR` with JSON text | Works offline; the app never queries inside the JSON |
| 5 | CSV export | DuckDB `COPY` vs. Python `csv` | Python `csv.DictWriter` | Rows are already assembled in Python with derived fields (evidence text, role labels); simpler and testable |
| 6 | Remote status when rules say UNKNOWN | Leave UNKNOWN vs. use the LLM's `work_arrangement` | Use LLM value only when rules say UNKNOWN | DESIGN data-flow step 4; rules stay authoritative when they decide |
| 7 | Default sort of the parent query vs. `R` child | Only add `DD` child vs. both `DD` and `R` | Both, as designed | LinkedIn's default guest sort isn't documented; both sorts maximise coverage on capped leaves |
| 8 | Extra test files outside the manifest | Leave `llm_classifier.py` at 32% and `cli.py` at 0% vs. add `test_llm_classifier.py`, `test_cli.py` | Add both | The LLM adapter is the only path to LATAM_FRIENDLY; untested failure handling there is the riskiest gap |
| 9 | Live smoke test location | New file vs. `@pytest.mark.live` test in the parser test file | Parser test file | DESIGN lists it in the strategy but not the manifest; smallest change |
| 10 | Golden set content | Wait for real data vs. ship synthetic seed | 32 synthetic cases covering the FR4.8 mix + 2 adversarial (prompt injection, mixed signals); a test skips until ≥ 30 real cases exist | Real descriptions need a run and human labels; the skip keeps the gap visible |
| 11 | "Unknown technology terms" review file (DEFINE SHOULD) | Skip vs. simple CamelCase/suffix heuristic | Heuristic, terms in ≥ 3 qualified jobs → `review/unknown_terms.csv` | Cheap, no false effect on counts; helps grow the list |
| 12 | LLM credential failure | Keep calling (every job fails) vs. disable for the run | Disable on 401/403/404, record reason in run message and report | Avoids thousands of failing calls; jobs fall to UNCLEAR safely; `reclassify` fixes later |
| 13 | Estimate assumptions for `--dry-run` | No estimate vs. rough formula | Formula with stated assumptions (35% title match, 80% LLM, 1.3 parent-first overhead, $0.00033/call) | DESIGN asks for an estimate; numbers labelled "rough" |

---

## Deviations from Design

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `selectolax.lexbor` instead of `selectolax.parser` | Backend removed in selectolax 1.0 | None (same selectors) |
| Two extra test files | Coverage of the LLM adapter and CLI | More tests; no behaviour change |
| `boundary_titles` table added to the schema | Needed to build `review/role_boundary.csv` per run | Additive |
| `classifications.reasoning` column added | Shows the model's short reason in `jobs_all.csv` for audits | Additive |
| `runs.mode` and `runs.message` columns added | Separate `count` runs from full runs; surface pause/LLM messages in the report | Additive |

---

## Blockers (if any)

No build blockers. Two open items need the owner before relying on results (they don't stop the build):

| Item | Required Action | Owner |
|---------|-----------------|-------|
| LLM golden test not run (`pytest -m llm tests/golden`) | Put `ANTHROPIC_API_KEY` in `.env`, run the test (~32 Haiku calls, well under $0.05). Until then LATAM-friendly labelling is unverified against the zero-leak target | Diego |
| Real golden cases: 0 of 30 | After the first run, copy ≥ 30 real descriptions into `tests/golden/cases.yaml` (`synthetic: false`) with hand labels, including restrictive, implied, misleading and LATAM-friendly ones | Diego |

---

## Acceptance Test Verification

| ID | Scenario | Status | Evidence |
|----|----------|--------|----------|
| AT-001 | Count funnel | ✅ Pass | `test_count_only_writes_six_rows`; real `jobscan count` produced 6 rows incl. "11,000+" lower bounds |
| AT-002 | Full run happy path | ✅ Pass | `test_full_run_happy_path` (all tables, report + 4 CSVs + 3 review files) |
| AT-003 | Pagination limit split | ✅ Pass | `test_split_order…`, `test_capped_slice_is_split_and_reported` (depths 0–3, capped leaves listed in report) |
| AT-004 | No duplicates | ✅ Pass | `test_dedup_across_slices` (job 27 in 2 slices → 1 row, 2 sightings) |
| AT-005 | Explicit restriction | ✅ Pass | `test_clear_restrictions`, golden `explicit_*`, integration job 10 (method `rules`) |
| AT-006 | USC/GC shorthand | ✅ Pass | `test_clear_restrictions["USC/GC only, no C2C."]`, golden `explicit_usc_gc` |
| AT-007 | Implied restriction → LLM | ✅ Pass (fake LLM) | Integration job 4 ("residents of CA, NY, TX" → method `llm`, US_CA_ONLY); real-model check pending (`-m llm`) |
| AT-008 | Negated positive | ✅ Pass | Rule `not_open_outside` (clear), golden `negated_not_open_outside` |
| AT-009 | Misleading positive | ✅ Pass (rules side) | Rules don't decide; golden `misleading_*` expects UNCLEAR from the LLM (pending `-m llm`) |
| AT-010 | Negated restriction | ✅ Pass | Negation → hint only; `test_llm_path_used_when_no_clear_rule` |
| AT-011 | Restriction inside stock text | ✅ Pass | `test_restriction_inside_stock_text_still_counts`, golden `stock_eeo_restriction` |
| AT-012 | Made-up quote | ✅ Pass | `test_fake_quote_downgrades`, `test_fake_quote_from_llm_is_downgraded` (end to end) |
| AT-013 | Low confidence | ✅ Pass | `test_low_confidence_downgrades` |
| AT-014 | LLM off | ✅ Pass | `test_llm_off_never_latam`, `test_no_llm_run_never_latam` |
| AT-015 | Hidden unclear | ✅ Pass | `test_unclear_hidden_by_default_and_shown_on_request` |
| AT-016 | Not really remote | ✅ Pass | `test_remote_status` (hybrid, military-spouse case), integration hybrid jobs excluded |
| AT-017 | Ambiguous tech names | ✅ Pass | `test_ambiguous_names`, `test_boundaries` |
| AT-018 | Tech counted per job | ✅ Pass | `test_counted_once_per_job_with_mention_count` |
| AT-019 | Resume | ✅ Pass | `test_block_pauses_run_and_resume_repeats_no_successful_request` (no list/count page or successful detail requested twice) |
| AT-020 | Blocking | ✅ Pass | `test_stops_after_consecutive_blocks`, integration pause with exit code 3 |
| AT-021 | Role boundary | ✅ Pass | `test_ml_engineer_is_boundary_for_ai` |
| AT-022 | Gig post exclusion | ✅ Pass | `test_title_matching["AI Trainer – Remote"]` |
| AT-023 | Golden set gate | ⚠️ Partial | Offline golden gate passes 47/47; LLM golden and ≥ 30 real cases pending (Blockers) |
| AT-024 | Closed post | ✅ Pass | `test_closed_detail`; integration job 7 excluded from qualified |

---

## Performance Notes

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| `count` mode | ≤ 10 min | 6 requests ≈ 25 s at 2–5 s delay | ✅ |
| Full first run | ≤ 6 h | Not measured (needs a real run). DESIGN estimate 6–7 h | ⏳ Measure on first run |
| Test suite | — | 45 s | ✅ |
| LLM cost per full first run | ≈ $1.5 | Not measured (no key) | ⏳ |

---

## Data Quality Results (if applicable)

### dbt Build Results

```text
N/A (no dbt models)
```

### SQL Lint Results

```text
N/A (sqlfluff not configured); schema.sql executed successfully in DuckDB 1.5.6 and is covered by store/integration tests
```

### Data Quality Checks

| Check | Tool | Result | Details |
|-------|------|--------|---------|
| Null `job_id` | Pipeline gate (`quality_violations`) | ✅ | 0 in integration runs |
| Unique `job_id` | Primary key | ✅ | Dedup test |
| Every role-matched job with details classified | Pipeline gate | ✅ | Run fails otherwise |
| LATAM_FRIENDLY ⇒ method llm and quotes verified | Table CHECK | ✅ | `test_check_constraint_blocks_unverified_latam` |
| Markup change detection | `MarkupChangedError` (> 20% empty descriptions) | ✅ | Code path; live smoke test passes today |

### Pipeline Metrics

| Metric | Value |
|--------|-------|
| Tests passed | 221/221 |
| Coverage | 92% |
| SQL lint violations | N/A |

---

## Final Status

### Overall: ✅ COMPLETE

**Completion Checklist:**

- [x] All tasks from manifest completed
- [x] All verification checks pass (ruff, mypy, pytest)
- [x] All tests pass
- [x] No blocking issues for the build
- [x] Acceptance tests verified (AT-023 partial: owner actions listed)
- [ ] Ready for /ship: after the first real run, the LLM golden test and ≥ 30 real golden cases

---

## Next Step

**Before shipping:** add `ANTHROPIC_API_KEY` to `.env`, run `.venv/bin/pytest -m llm tests/golden`, run `jobscan run` (or a smaller `--role ... --country Canada` run first), then label ≥ 30 real descriptions.

**Then:** `/ship .claude/sdd/features/DEFINE_LINKEDIN_REMOTE_JOB_SCANNER.md`
