# DEFINE: LinkedIn Remote Job Scanner

> An on-demand CLI that counts, collects and classifies remote US/Canada LinkedIn jobs for Data Engineer, Forward Deployed Engineer and AI Engineer, keeps only the ones that explicitly accept LATAM/Brazil/worldwide candidates in the "can apply" list, and ranks the technologies they ask for.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | LINKEDIN_REMOTE_JOB_SCANNER |
| **Date** | 2026-10-31 |
| **Author** | define-agent (from PRD-001 v1.2, owner Diego P. Mayer) |
| **Status** | ✅ Complete (Built) |
| **Clarity Score** | 14/15 |
| **Source** | `docs/prd/PRD-001-linkedin-remote-job-market.md` (input type: `direct_requirement`, a structured PRD) |

---

## Problem Statement

A Brazil-based data professional can't tell how many remote US/Canada Data Engineer, Forward Deployed Engineer and AI Engineer jobs they are actually allowed to apply to. LinkedIn's logged-out counts are capped ("10,000+") and loosely matched; its "Remote" filter lets hybrid jobs through; and whether a company hires from LATAM is buried in free-text descriptions. Checking by hand across thousands of posts isn't feasible.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Diego (primary) | Data professional in Brazil looking for remote US/Canada roles | Spends hours opening posts only to find "US citizens only" / "no sponsorship" at the bottom; can't trust LinkedIn's counts; doesn't know which tools to prioritise learning |
| Diego as analyst (secondary use) | Studies the remote job market | No reliable count split by role, country and eligibility; no technology demand ranking for LATAM-eligible vs US-only jobs |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | **G1 Counts:** for each of the 6 searches (3 roles × 2 countries), report a funnel: LinkedIn displayed count → collected → title-matched → qualified (remote), with qualified split into `LATAM_FRIENDLY` / `UNCLEAR` / `US_CA_ONLY` |
| **MUST** | **G2 Collection:** collect every reachable matching job post (list pages + full description) without duplicates, splitting searches into slices of under 1,000 results to get past LinkedIn's per-query limit |
| **MUST** | **G3 Eligibility (safe by default):** label every qualified job; rules may only *exclude* (`US_CA_ONLY`); `LATAM_FRIENDLY` only from the LLM with an exact, verified quote and confidence ≥ 0.8; explicit **and implied** US/CA citizenship / residency / visa / work-authorization requirements → `US_CA_ONLY` |
| **MUST** | **G4 Remote check:** reclassify each job from its description as REMOTE / HYBRID / ONSITE / UNKNOWN; hybrid and on-site are excluded from qualified counts |
| **MUST** | **G5 Technologies:** count jobs mentioning each technology from a curated list (≥ 70 entries, 12 categories), ranked overall, per role, per eligibility label and per country |
| **MUST** | **G6 Outputs:** DuckDB store, `can_apply.csv` (LATAM-friendly only, with evidence), `jobs_all.csv`, `counts.csv`, `technologies.csv`, Markdown report per run |
| **MUST** | **G7 Operation:** one on-demand command, all roles/keywords/patterns/limits in YAML config, resumable after interruption, polite request rate |
| **MUST** | **G8 Golden test set:** ≥ 30 labelled real descriptions that must pass before any rule or prompt change is accepted |
| **SHOULD** | `count` subcommand (counts only, minutes); `report` and `reclassify` subcommands working from stored data |
| **SHOULD** | Audit sample in every report (10 random jobs per label with evidence) |
| **SHOULD** | Log candidate titles near the role boundary (ML Engineer, solutions engineer…) and unknown technology terms to review files |
| **COULD** | Self-contained HTML report with charts |
| **COULD** | Mark technologies as *required* vs *nice to have* from section headings |
| **COULD** | Optional sub-location slicing (states/provinces) behind a config flag |

---

## Success Criteria

- [ ] **0** `US_CA_ONLY` jobs in the "can apply" list across the golden test set; ≤ 2% (≤ 1 of 50) in a manual audit of 50 random `LATAM_FRIENDLY` jobs
- [ ] **100%** of golden-set explicit and implied restriction cases labelled `US_CA_ONLY`; ≥ 95% recall in a manual audit of 50 jobs with restrictive text
- [ ] **100%** of golden-set negated/misleading positives ("not open to candidates outside the US", "offices in Brazil") **not** labelled `LATAM_FRIENDLY`
- [ ] **100%** of `LATAM_FRIENDLY` jobs have ≥ 1 evidence quote that is an exact substring of the description
- [ ] Count funnel produced for **6/6** searches, each role reported separately
- [ ] Coverage ≥ **95%** of displayed count on slices whose displayed count is exact (< 1,000)
- [ ] Detail fetch success ≥ **98%** of title-matched jobs
- [ ] Hybrid/on-site jobs wrongly counted as remote ≤ **5%** in an audit of 50
- [ ] Technology extraction recall ≥ **90%** on the top-50 technologies, audit of 30 descriptions
- [ ] An interrupted run resumes with **0** repeated detail requests
- [ ] Full run (≈ 4,500 detail pages) completes in ≤ **6 hours** at the default rate; `count` mode in ≤ **10 minutes**
- [ ] Stops after ≤ **N** consecutive block responses (429/999; N configurable, default 5) with no data loss

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Count funnel | Default config with 3 roles × 2 countries, past 30 days | `jobscan count` | `counts.csv` has 6 rows with `displayed_count_raw`, parsed number and `is_lower_bound` (true for "10,000+") |
| AT-002 | Full run happy path | Empty database | `jobscan run` | DuckDB contains runs, searches, slices, jobs, job_details, classifications, job_technologies; report and 4 CSVs written under `reports/<run_id>/` |
| AT-003 | Pagination limit | A slice whose displayed count is ≥ 1,000 | Collection reaches `start=990` with cards still returned | Slice is split by `f_E`, then `f_JT`, then `sortBy=DD`; split recorded; `hit_cap=true` reported if still capped |
| AT-004 | No duplicates | The same job appears in 3 slices and 2 roles | Run completes | One `jobs` row; 3 `job_sightings` rows; counted under both roles, once in overall totals |
| AT-005 | Explicit restriction | Description says "Must be a US citizen or green card holder" | Classification | `US_CA_ONLY`, method `rules`, evidence snippet stored, no LLM call |
| AT-006 | US-staffing shorthand | Description says "USC/GC only, no C2C" | Classification | `US_CA_ONLY`, method `rules` |
| AT-007 | Implied restriction | Description lists "Open to residents of CA, NY, TX" and only W-2 benefits; no listed restrictive phrase | Classification | Sent to the LLM; result `US_CA_ONLY` with `restriction_type` `location_list` or `employment_type` |
| AT-008 | Negated positive | Description says "This role is not open to candidates outside the US" | Classification | **Not** `LATAM_FRIENDLY` (expected `US_CA_ONLY`) |
| AT-009 | Misleading positive | Description says "We have offices in São Paulo and customers across LATAM", nothing about hiring | Classification | `UNCLEAR` (not `LATAM_FRIENDLY`) |
| AT-010 | Negated restriction | Description says "You don't need to be a US citizen; we hire contractors across the Americas via Deel" | Classification | No rules decision; LLM returns `LATAM_FRIENDLY` with the Deel sentence as an exact quote |
| AT-011 | Restriction inside stock text | EEO paragraph contains "Applicants must be authorized to work in the US" | Classification | `US_CA_ONLY` (scan runs before stock-text handling) |
| AT-012 | Made-up quote | LLM returns `LATAM_FRIENDLY` with a quote not in the description | Quote verification | Label downgraded to `UNCLEAR`; `quotes_verified=false` |
| AT-013 | Low confidence | LLM returns `LATAM_FRIENDLY` with confidence 0.6 | Threshold check | Downgraded to `UNCLEAR` |
| AT-014 | LLM off | Config `llm.enabled: false` | Run | No job is `LATAM_FRIENDLY`; jobs without a clear restriction are `UNCLEAR`, method `rules-fallback` |
| AT-015 | Hidden unclear | Run produced `UNCLEAR` jobs | `jobscan report` without flags | `UNCLEAR` section absent from the report; present with `--include-unclear`; never in `can_apply.csv` |
| AT-016 | Not really remote | Remote-filtered card whose description says "hybrid, 3 days in office" | Remote check | `HYBRID`; excluded from qualified counts |
| AT-017 | Ambiguous tech names | Description mentions "Go-to-market" and "spark joy" | Technology extraction | No `Go` or `Spark` match; "Golang" and "PySpark" would match |
| AT-018 | Tech counted per job | Description mentions Python 7 times | Technology extraction | Python counted once for that job; `mention_count=7` stored |
| AT-019 | Resume | Run killed after 1,200 of 3,000 detail fetches | `jobscan run --resume` | Continues at fetch 1,201; 0 repeated detail requests |
| AT-020 | Blocking | Endpoint returns HTTP 999 five times in a row | Fetching | Exponential backoff then clean stop; progress saved; error count in `runs` |
| AT-021 | Role boundary | Card titled "Machine Learning Engineer" (no "AI") | Title matching with default config | Not matched to AI Engineer; logged to the role-boundary review file |
| AT-022 | Gig post exclusion | Card titled "AI Trainer – Remote" | Title matching | Excluded from AI Engineer |
| AT-023 | Golden set gate | Rules or prompt version changed | `pytest tests/golden` | All ≥ 30 cases pass, otherwise the change is rejected |
| AT-024 | Closed post | Detail page shows "No longer accepting applications" | Detail parsing | `is_closed=true`; excluded from qualified counts |

---

## Out of Scope

- Logged-in scraping, LinkedIn accounts, cookies, CAPTCHA solving, proxy rotation or any other block evasion
- Scheduled/daily runs and trend charts (data model keeps every run so this can be added later)
- Sources other than LinkedIn (Indeed, Wellfound, company ATS APIs, LATAM boards): future work
- On-site and hybrid jobs; countries other than the US and Canada
- Roles other than Data Engineer, Forward Deployed Engineer and AI Engineer (Analytics Engineer, pure ML Engineer, Data Scientist, data architect: future, via config)
- Auto-apply, contacting recruiters, storing personal data about individuals (recruiter names/profiles)
- Salary extraction and normalisation
- Dashboards (Streamlit/Evidence) and any hosted/cloud deployment

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Technical | Only LinkedIn's logged-out endpoints: `/jobs/search` (count), `/jobs-guest/jobs/api/seeMoreJobPostings/search` (lists), `/jobs-guest/jobs/api/jobPosting/<id>` (detail) | HTML parsing with saved fixtures; parser changes when LinkedIn changes markup |
| Technical | At most ~1,000 results per query (`start=1000` → HTTP 400) | Adaptive slicing required; coverage metric must be reported |
| Technical | Keyword search ignores quotes / matches loosely | Role is decided by title pattern after collection, never by LinkedIn's count |
| Technical | Python 3.10 (installed), local machine (WSL2); stack: `httpx`, `selectolax`/BeautifulSoup, `pydantic` v2, DuckDB, `typer`, `anthropic` SDK, `pytest` | Design must fit this stack |
| Technical | LLM: Claude Haiku (`claude-haiku-5-5`) with structured JSON output; `ANTHROPIC_API_KEY` from env/`.env`, never committed | Prompt + schema design; cache by description + prompt-version hash |
| Rate | 1 request at a time, random 2–5 s delay, exponential backoff on 429/999/5xx, stop after N consecutive blocks | Full run ≈ 4.5 h; must be resumable and show the estimate before starting |
| Legal | LinkedIn's terms forbid automated scraping | Personal research use only; slow rate; no evasion; no personal data about individuals |
| Cost | Hard cap on LLM calls per run (config) | When the cap is reached, remaining jobs are `UNCLEAR` (never `LATAM_FRIENDLY`) |
| Timeline | None stated | Delivered in milestones M1–M6 (PRD §17) |
| Resource | Single developer; no cloud budget | Local-only, file-based storage |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | `src/jobscan/` (package), `config/` (searches.yaml, technologies.yaml, eligibility rules), `data/` (DuckDB + raw HTML, gitignored), `reports/` (outputs), `tests/` with `tests/fixtures/` (saved HTML) and `tests/golden/` (eligibility golden set) | Default chosen by define-agent: the project is empty, and a `src/` layout keeps the CLI package separate from config and data |
| **KB Domains** | `python` (clean-architecture, error-handling, file-parser, dataclasses, type-hints), `pydantic` (base-model, validators, llm-output-validation, extraction-schema), `prompt-engineering` (structured-extraction, output-formatting, validation-prompts, system-prompts), `genai` (guardrails, evaluation-framework), `modern-stack` (duckdb, duckdb-patterns, local-first-analytics), `data-quality` (quality-dimensions, schema-validation), `testing` (pytest-basics, fixtures, parametrize, integration-tests, mocking) | Design should pull patterns for the HTTP client + parser layers, the LLM classifier with validated output, the DuckDB schema, and the golden-set tests |
| **IaC Impact** | None | Local CLI; no cloud resources. Only `.gitignore` entries for `data/`, `.env`, `tools/*/.venv` |

---

## Data Contract (if applicable)

### Source Inventory
| Source | Type | Volume | Freshness | Owner |
|--------|------|--------|-----------|-------|
| LinkedIn count page `/jobs/search` | HTML (logged out) | 6 requests per run (+ 1 per slice) | Snapshot at run time | LinkedIn (external, no SLA) |
| LinkedIn list API `seeMoreJobPostings/search` | HTML fragment, 10 cards/page (`start` offset, step 10; verified in Design) | ≈ 6 searches × up to 1,000 cards per slice; ~15–25k cards/run before dedup (estimate) | Snapshot at run time | LinkedIn |
| LinkedIn detail API `jobPosting/<id>` | HTML fragment | ≈ 4,500 title-matched jobs/run (estimate) | Snapshot at run time; reused across runs unless `--refresh` | LinkedIn |
| Anthropic Messages API (Claude Haiku) | JSON | ≤ one call per unique description not excluded by rules, capped per run | Cached per description + prompt version | Anthropic |

### Schema Contract
| Column | Type | Constraints | PII? |
|--------|------|-------------|------|
| `jobs.job_id` | VARCHAR (LinkedIn numeric ID) | PRIMARY KEY, NOT NULL | No |
| `jobs.title`, `jobs.company`, `jobs.location_text`, `jobs.url` | VARCHAR | title, company, url NOT NULL | No (company-level only) |
| `jobs.posted_at` | DATE | nullable (not always present) | No |
| `job_details.description_text` | VARCHAR | NOT NULL when `fetched_ok` | No; recruiter names/emails in text are not extracted into columns |
| `job_details.description_html_gz` | BLOB | gzip of raw response | No |
| `job_details.is_closed` | BOOLEAN | NOT NULL | No |
| `classifications.remote_status` | ENUM(REMOTE, HYBRID, ONSITE, UNKNOWN) | NOT NULL | No |
| `classifications.eligibility_label` | ENUM(LATAM_FRIENDLY, US_CA_ONLY, UNCLEAR) | NOT NULL | No |
| `classifications.method` | ENUM(rules, llm, rules-fallback) | NOT NULL | No |
| `classifications.confidence` | DECIMAL(3,2) | 0.00–1.00; NULL for rules | No |
| `classifications.restriction_type` | ENUM(citizenship, residency, work_authorization, visa, clearance, employment_type, location_list, office_presence, none) | NOT NULL | No |
| `classifications.evidence_json`, `matched_phrases_json` | JSON | `LATAM_FRIENDLY` requires ≥ 1 verified quote | No |
| `classifications.rules_version`, `prompt_version`, `llm_model` | VARCHAR | rules_version NOT NULL | No |
| `job_technologies (job_id, tech_id)` | VARCHAR, INT | composite PK; `mention_count` INT ≥ 1 | No |
| `searches.displayed_count_raw` / `displayed_count` / `is_lower_bound` | VARCHAR / INT / BOOLEAN | raw NOT NULL | No |

### Freshness SLAs
| Layer | Target | Measurement |
|-------|--------|-------------|
| Raw (HTML responses) | Written before parsing, same run | `fetched_at` per response |
| Parsed (jobs, job_details) | Available at end of collection/fetch stages | stage completion recorded in `runs` |
| Outputs (CSVs, report) | Generated at end of run, or on demand via `report` | report header shows run start/end time |

On-demand only: no time-of-day SLA. Each report states the time its data was collected.

### Completeness Metrics
- Coverage ≥ 95% of displayed count on slices with an exact (< 1,000) displayed count
- ≥ 98% of title-matched jobs have a successful detail fetch
- 0 null `job_id`; 0 duplicate `job_id` in `jobs`
- 100% of qualified jobs have a classification row with non-null label, method and rules_version
- Slices that still hit the 1,000 limit are listed in the report (never silently truncated)

### Lineage Requirements
- Every classification links to the run, rules_version, prompt_version and llm_model that produced it
- Raw HTML kept so `reclassify` / re-parsing reproduces outputs without fetching again
- Each job keeps the slices and runs it was seen in (`job_sightings`)
- Config hash stored per run

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | The three logged-out endpoints stay available without login (tested 2026-10-31: HTTP 200) | Tool can't collect; would need another source (Indeed connector, ATS APIs) | [x] (as of 2026-10-31) |
| A-002 | Slicing by `f_E`, `f_JT` and sort brings each slice under 1,000 results | Coverage drops for big searches (e.g. US Data Engineer 11,000+); would need sub-location slicing (COULD goal) | [ ] |
| A-003 | 2–5 s between requests avoids long blocks for a ~4.5 h run | Runs stop early; would need slower rate or splitting a run across days by role (`--role`) | [ ] |
| A-004 | Eligibility, when stated, is in the description text | Many jobs end as `UNCLEAR`; "can apply" list smaller than reality (acceptable by design: safe default) | [ ] |
| A-005 | Claude Haiku with the FR4 prompt meets the golden-set targets (0 leaks, 100% restriction recall) | Need a stronger model for the LLM pass, or more few-shot examples; higher cost | [ ] |
| A-006 | LinkedIn job IDs are stable across runs | Duplicates across runs; would need a secondary key (company + normalised title + description hash, PRD §14) | [ ] |
| A-007 | Detail page markup exposes title, description, seniority, employment type and closed status as in the 2026-10-31 sample | Parser changes; fields may be null | [x] (title + description confirmed; criteria fields not yet parsed) |
| A-008 | Title patterns (§9 of the PRD) separate the roles well enough | Counts inflated or deflated; mitigated by role-boundary review file | [ ] |
| A-009 | ≈ 4,500 title-matched jobs per full run (3 roles × 2 countries) | Run time and LLM cost scale with the real number; estimate shown before each run | [ ] |
| A-010 | Personal, low-rate research use is an acceptable risk under LinkedIn's terms | Account/IP blocking or legal exposure; owner has accepted this risk (PRD §14) | [x] (accepted by owner) |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Specific, backed by tests: capped/loose counts, noisy remote filter, eligibility hidden in text |
| Users | 2 | One clear persona with concrete pain points; it's a personal tool, so there are no other user groups to cover |
| Goals | 3 | 8 MUST goals mapped to PRD FRs, each with clear inputs and outputs |
| Success | 3 | 12 numeric criteria, including the zero-leak eligibility target |
| Scope | 3 | Roles, countries, work type and eligibility rules explicit; detailed out-of-scope list |
| **Total** | **14/15** | Passes the 12/15 gate |

---

## Open Questions

None blocking. Ready for Design.

These have defaults accepted from PRD §16 (the owner can override them in config at any time):

| # | Question | Default used |
|---|---|---|
| G-Q1 | `UNCLEAR` jobs in the "can apply" list? | No; hidden section, `--include-unclear` shows it |
| G-Q2 | Contract (1099/C2C) roles? | Kept and tagged; "no C2C" text is still a restriction |
| G-Q3 | Default time window | Past 30 days |
| G-Q4 | Manager/director titles | Excluded ("manager", "director", "head of"); "lead/staff/principal" kept |
| G-Q5 | Job matching several roles | Counted under each role, once in overall totals |
| DE-Q1–Q5 | Data Engineer title boundary | No Analytics Engineer, no BI developer, no data architect; yes ETL / DW / platform / "Software Engineer, Data" |
| FDE-Q1–Q5 | FDE title boundary | Only "forward deployed"/"FDE" titles; look-alikes logged; travel and US hours are hints, not restrictions; no non-engineer FDE titles |
| AI-Q1–Q6 | AI Engineer title boundary | No pure ML Engineer (logged); yes AI/ML, "Software Engineer (AI)", research engineer; no research scientist; gig posts excluded; tech split LLM vs ML |

Resolved in Design: the list API returns 10 cards per page and `start` is an offset with step 10 (the earlier "30" counted CSS class matches).

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-10-31 | define-agent | Initial version from PRD-001 v1.2 |
| 1.1 | 2026-10-31 | design-agent | Status → Complete (Designed); page size corrected to 10 cards; start-step question resolved |
| 1.2 | 2026-10-31 | build-agent | Status → Complete (Built) |

---

## Next Step

**Ready for:** `/ship .claude/sdd/features/DEFINE_LINKEDIN_REMOTE_JOB_SCANNER.md` (after the owner actions in `.claude/sdd/reports/BUILD_REPORT_LINKEDIN_REMOTE_JOB_SCANNER.md`)
