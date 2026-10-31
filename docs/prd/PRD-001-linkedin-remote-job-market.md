# PRD-001 — LinkedIn Remote Job Market Scanner (US/Canada, LATAM-eligible)

| Field | Value |
|---|---|
| Status | Draft v1.2 (added AI Engineer; open questions split per role) |
| Date | 2026-10-31 |
| Owner | Diego P. Mayer |
| Next step | SDD workflow: `/brainstorm` (optional) → `/define` → `/design` → `/build` → `/ship` |

---

## 1. Summary

An on-demand command-line tool that searches LinkedIn's public (logged-out) job pages for **remote** jobs posted in the **United States or Canada** for three roles: **Data Engineer**, **Forward Deployed Engineer** and **AI Engineer**. For each run it:

1. **Counts** open jobs for each search and filter combination.
2. **Extracts** every matching job post, including the full description.
3. **Classifies** whether the company accepts candidates from **LATAM / Brazil / worldwide / nearshore**, or only accepts people who live in, are citizens of, or are authorized to work (or hold a visa) in the US/Canada, whether that is stated explicitly or implied. Only jobs that **explicitly** accept LATAM/worldwide candidates go in the "can apply" list.
4. **Counts tools and technologies** mentioned across the job descriptions.

The output answers one question: *"Right now, how many remote US/Canada Data Engineer, Forward Deployed Engineer and AI Engineer jobs could a candidate in Brazil apply to, and which technologies do they ask for?"*

## 2. Problem

- LinkedIn's job-count banner is not trustworthy for this purpose. For logged-out users it is capped ("10,000+"), it matches keywords loosely, and it can't filter by *who is allowed to apply*.
- LinkedIn's "Remote" filter lets through hybrid and on-site jobs (see §5).
- Whether a candidate from Brazil can apply is only stated in the free-text description, and many posts don't state it at all. Checking this by hand across hundreds of posts isn't practical.
- There's no easy way to see which tools are actually in demand for these roles in the remote US/Canada market.

## 3. Goals and non-goals

### Goals
| # | Goal |
|---|---|
| G1 | Give a reliable count of open jobs per search/filter, separating *LinkedIn's displayed count* from *jobs we verified ourselves* (§7.1). |
| G2 | Collect every reachable job post that matches the filters, with its full description and metadata, without duplicates. |
| G3 | Label each job's eligibility as **LATAM-friendly**, **US/CA-only**, or **Unclear**, keeping the evidence text. |
| G4 | Rank tools and technologies by how many jobs mention them, overall and per role / eligibility label. |
| G5 | Run on demand with one command; a stopped or failed run can be resumed. |

### Non-goals (v1)
- No logged-in scraping, no LinkedIn account use, no CAPTCHA bypass, no proxy rotation for evasion.
- No scheduled/daily runs (on-demand only; the data model still keeps each run so history can be added later).
- No auto-apply, no contacting recruiters, no collection of personal data about individuals (recruiter names or profiles).
- No job boards other than LinkedIn in v1 (Indeed etc. listed as future work, §15).
- No on-site or hybrid jobs; no countries other than US and Canada.

## 4. Users and use cases

**Primary user:** a data professional based in Brazil looking for remote US/Canada roles.

| ID | Use case |
|---|---|
| UC1 | "How many remote Data Engineer jobs in the US are open this week, and how many of them accept LATAM candidates?" |
| UC2 | "Give me the list of LATAM-friendly Forward Deployed Engineer jobs with links, so I can apply." |
| UC2b | "Which AI Engineer jobs accept LATAM candidates, and do they ask for LLM/RAG skills or classic ML skills?" |
| UC3 | "What are the top 30 technologies in LATAM-friendly Data Engineer posts, compared with US-only posts?" |
| UC4 | "Re-run with a different keyword or time window without changing code." |

## 5. Feasibility evidence (tests run 2026-10-31)

All tests used plain HTTP `GET` requests, logged out, with a browser User-Agent header.

| Test | Endpoint | Result |
|---|---|---|
| Count banner | `https://www.linkedin.com/jobs/search?keywords=…&location=…&f_WT=2&f_TPR=…` | HTTP 200. Count is in `span.results-context-header__job-count`. Exact below about 1,000 (e.g. `797`), otherwise a lower bound (`2,000+`, `4,000+`, `10,000+`, `11,000+`). |
| Job list (paginated) | `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?…&start=N` | HTTP 200 with **10** job cards per page (`div.base-card[data-entity-urn="urn:li:jobPosting:<id>"]`); `start` is a result offset with step 10 (re-verified in Design; an earlier "30" counted CSS class matches). `start=990` works; **`start=1000` returns HTTP 400**, so each query reaches at most about 1,000 jobs. |
| Job detail | `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>` | HTTP 200. Title in `top-card-layout__title`; full description in `show-more-less-html__markup` (about 5 KB of text in the sample). |
| Remote filter accuracy | `f_WT=2` | **Noisy.** The first "remote" result (USAA) said "may offer remote or hybrid flexibility for active-duty military spouses", so it was effectively not remote. |
| Eligibility signal | description text | Present as free text, e.g. "USAA does not provide visa sponsorship for this role." |
| Keyword precision | `keywords="forward deployed engineer"` | **Loose matching.** US remote, last 30 days: FDE showed 10,000+ vs Data Engineer 11,000+, nearly identical. Quotes are ignored and results fall back to broad matches, so title filtering after collection is required. |

Observed displayed counts (remote, `f_WT=2`):

| Keyword | Location | 24 h | 7 days | 30 days |
|---|---|---|---|---|
| "data engineer" | United States | 4,000+ | 10,000+ | 11,000+ |
| "data engineer" | Canada | 536 | 2,000+ | 5,000+ |
| "forward deployed engineer" | United States | 4,000+ | 9,000+ | 10,000+ |
| "forward deployed engineer" | Canada | 507 | 2,000+ | 5,000+ |
| "ai engineer" | United States | 5,000+ | 11,000+ | 11,000+ |
| "ai engineer" | Canada | 403 | 2,000+ | 5,000+ |

AI Engineer title sample (first 30 cards, US, 7 days): AI Engineer, Machine Learning Engineer, AI/ML Engineer, Lead AI/ML Engineer, Generative AI & Machine Learning Engineer, Software Engineer (AI). The search mixes AI Engineer and ML Engineer titles, so the title pattern must draw the boundary (§9, §16.4).

**What this means for the design:** (a) a single query can't collect everything, so searches must be split into slices of under 1,000 jobs (§7.2); (b) the displayed count is only a reference number; (c) title matching and remote checks must run on the collected data.

## 6. Scope and filters

| Dimension | Rule |
|---|---|
| Roles | **Data Engineer**, **Forward Deployed Engineer**, **AI Engineer**. Each role has search keywords and a title-match pattern in config (§9). |
| Work type | **Remote only**: LinkedIn `f_WT=2` at search time **and** a remote check on the description (FR5). Hybrid/on-site jobs are excluded from qualified counts. |
| Countries | **United States** and **Canada** only (`location=United States`, `location=Canada`; geoIds resolved at runtime and stored). |
| Eligibility | The "can apply" list contains **only LATAM-friendly** jobs. **Unclear** jobs are kept in a separate section that is hidden by default (`--include-unclear` shows it). **US/CA-only** jobs are counted for comparison but never appear in any "can apply" list. A job is US/CA-only when the text **states or implies** that the candidate must live in, be a citizen of, or hold work authorization/a visa for the US or Canada. |
| Time window | Configurable; default **past 30 days** (`f_TPR=r2592000`), the usual lifetime of a LinkedIn post. |

## 7. Functional requirements

### FR1 — Job counts
- **FR1.1** For every (role × country × time window) search, record LinkedIn's **displayed count** as raw text plus a parsed number and an `is_lower_bound` flag (true when it ends with `+`).
- **FR1.2** Report four counts for each search, at each step of the funnel:

| Metric | Definition |
|---|---|
| `displayed_count` | LinkedIn banner value (may be capped or inflated). |
| `collected_count` | Unique job IDs collected across all slices. |
| `role_matched_count` | Collected jobs whose **title** matches the role pattern. |
| `qualified_count` | Role-matched **and** confirmed remote **and** not expired, split by eligibility: LATAM-friendly / Unclear / US-CA-only. |

- **FR1.3** Report **coverage** = `collected_count / displayed_count` (when the displayed count is exact) and flag slices that hit the 1,000 limit.

### FR2 — Collecting job lists (with slicing)
- **FR2.1** Page through `seeMoreJobPostings/search` with `start` = 0, 25… (or the step the endpoint actually uses; detect it from the page size) until there are no cards or `start` > 990.
- **FR2.2** **Adaptive slicing:** if a query's displayed count is ≥ 1,000, or pagination reaches `start=990` with cards still returned, split it with more filters, recursively, until each slice is under 1,000:
  1. Experience level `f_E` = 1…6 (internship, entry, associate, mid-senior, director, executive)
  2. Job type `f_JT` = F, C, P, T (full-time, contract, part-time, temporary)
  3. Sort `sortBy=DD` (newest first) as the last resort for slices that are still capped
  4. Province/state sub-locations are **not** used by default: many remote posts are listed at country level ("United States") and would be lost. Optional, behind a config flag.
- **FR2.3** Remove duplicates by `job_id` across slices, searches and runs; keep which slices found each job.
- **FR2.4** Parse from each card: `job_id`, title, company name, company LinkedIn URL, location text, posted date (`datetime` attribute), job URL.

### FR3 — Job detail extraction
- **FR3.1** For every collected job that is **role-matched** (title filter first, to save requests), fetch `jobs-guest/jobs/api/jobPosting/<id>`.
- **FR3.2** Extract: title, company, location, full description (HTML and clean text), seniority level, employment type, job function, industries, applicant count text if shown, posted date, and whether the post is closed ("No longer accepting applications").
- **FR3.3** Store the raw HTML response (compressed) so jobs can be re-parsed without fetching again.
- **FR3.4** If a job ID was already fetched successfully in an earlier run, reuse it unless `--refresh` is given.

### FR4 — Eligibility classification (hybrid, safe by default)

**Main principle:** an error should only ever cost you a job you could have applied to. It must never put a job you can't apply to in your list. So rules alone may only **exclude** jobs; only the LLM may label a job **LATAM_FRIENDLY**.

- **FR4.1** **Step 1: restriction scan on the full, unmodified text.** Before anything is removed (FR4.6), match the **US/CA restrictive** phrases from §8, case-insensitive, in English, Portuguese and Spanish. Output the matched phrases and a ±150-character snippet as evidence.
- **FR4.2** **Negation and context check on each restrictive match.** A match counts as a *clear restriction* only if:
  - it isn't negated within the same sentence ("not required", "no need to be", "regardless of citizenship", "you don't need to be a US citizen"), and
  - it isn't a question or a quote about something else (e.g. "we help US citizens file taxes" in a product description).
  Matches that fail either check are passed to the LLM as *hints*, not decisions.
- **FR4.3** **Decision logic:**

| Situation | Label | Method |
|---|---|---|
| At least one **clear restriction** (FR4.2) | `US_CA_ONLY` | rules (final; no LLM call needed) |
| Anything else: only positive signals, mixed signals, weak signals, negated matches, or **no signals at all** | Sent to the LLM | llm |
| LLM turned off, budget used up, or LLM error | `UNCLEAR` (**never** `LATAM_FRIENDLY`) | rules-fallback |

  - Positive phrases ("LATAM", "Brazil", "worldwide", "outside the US"…) are **never** enough to label a job LATAM-friendly. They are passed to the LLM as hints, because they often appear in negated sentences ("**not** open to candidates outside the US", "we **cannot** hire in LATAM") or with another meaning ("our office in São Paulo", "customers across LATAM").
- **FR4.4** **LLM pass:** Claude Haiku (`claude-haiku-5-5`) receives the full unmodified description, the job card location and title, and the rule hints. It returns structured JSON:
  ```json
  {
    "label": "LATAM_FRIENDLY | US_CA_ONLY | UNCLEAR",
    "confidence": 0.0,
    "restriction_type": "citizenship | residency | work_authorization | visa | clearance | employment_type | location_list | office_presence | none",
    "evidence_quotes": ["exact sentence(s) from the text"],
    "reasoning_short": "one or two sentences"
  }
  ```
  The prompt contains these instructions:
  - Label `US_CA_ONLY` if the text **states or implies** that the candidate must live in, be a citizen or permanent resident of, or hold work authorization or a visa for the US or Canada. Implied examples: W-2 / T4 employment only, US/Canadian payroll or benefits presented as the only option (401(k), US health insurance, RRSP), a list of allowed US states or Canadian provinces, required regular visits to a US/Canadian office, US-person / export-control rules, background checks that need an SSN/SIN, E-Verify.
  - Label `LATAM_FRIENDLY` **only** if the text explicitly says candidates from LATAM / Brazil / South America / anywhere / worldwide / outside the US-Canada can be hired (e.g. as contractors, through an EOR like Deel or Remote.com, or a nearshore model). Quote the sentence.
  - Mentions of LATAM, Brazil, etc. that describe offices, customers, markets or teams are **not** permission to hire there.
  - If neither is clear, label `UNCLEAR`. Don't guess.
  - Every `evidence_quotes` entry must be an exact substring of the description. The tool checks this; if a quote isn't found, the label is downgraded to `UNCLEAR` (protects against made-up quotes).
- **FR4.5** **Confidence threshold:** `LATAM_FRIENDLY` with `confidence < 0.8` (configurable) is downgraded to `UNCLEAR`. `US_CA_ONLY` is accepted at any confidence.
- **FR4.6** **Stock text handling:** EEO statements, "reasonable accommodation" paragraphs and benefits text are detected **only after** the restriction scan (FR4.1), and only used to stop *positive* phrases in them from counting as hints. Restrictions found inside stock text still count (e.g. "Applicants must be authorized to work in the US" inside an EEO paragraph).
- **FR4.7** **Caching and audit:** LLM results are cached by hash(description text + prompt version + model). Every classification stores `method` (rules / llm / rules-fallback), `rules_version`, `prompt_version`, `llm_model`, matched phrases, and evidence quotes.
- **FR4.8** **Golden test set:** the repository contains a labelled set of **at least 30 real descriptions** (saved HTML) that must pass in CI before a rules or prompt change is accepted. It must include at least:
  - 8 explicit restrictions (citizenship, green card, "authorized to work", "no sponsorship", clearance, "USC/GC only", W-2 only, Canadian PR)
  - 6 implied restrictions (state list, US benefits only, office visits, E-Verify/SSN, "US persons", T4 employee)
  - 4 negated or misleading positives ("not open to candidates outside the US", "cannot hire in LATAM", "offices in Brazil", "customers in Latin America")
  - 6 true LATAM-friendly posts (contractor via EOR, "anywhere in the Americas", nearshore, worldwide)
  - 4 truly silent posts (expected `UNCLEAR`)
  - 2 restrictions placed inside EEO/stock text

### FR5 — Remote check
- **FR5.1** Mark each job `REMOTE`, `HYBRID`, `ONSITE` or `UNKNOWN` from the description (e.g. "hybrid", "X days in office", "on-site", "relocation required", "remote flexibility for military spouses" → not REMOTE).
- **FR5.2** Only `REMOTE` and `UNKNOWN` jobs count toward `qualified_count`; `UNKNOWN` is reported separately.
- **FR5.3** "Remote, US only" / "Remote within Canada" are still `REMOTE` for work type; the country restriction is handled by FR4.

### FR6 — Technology extraction and counts
- **FR6.1** Match descriptions against a curated **technology list** (§10): a canonical name, a category, aliases and regex patterns.
- **FR6.2** Count **jobs mentioning each technology** (each job counts once per technology), not raw mention totals.
- **FR6.3** Disambiguate risky names with context rules: `Go` (only "Golang"/"Go language"/listed among languages), `R` (only listed among languages), `Spark` (not "spark joy"), `Snowflake`, `Looker`, `Glue` (with AWS context), `Airflow`, `Dagster`, `dbt`.
- **FR6.4** Optionally mark *required* vs *nice to have* when the mention appears under a "Requirements / Must have" or "Nice to have / Bonus" heading (best-effort).
- **FR6.5** Unknown candidates: log frequent capitalised words/terms that aren't in the list, to a review file, so the list can be extended.
- **FR6.6** Rankings: overall; by role; by eligibility label; by country; with share of jobs (%).

### FR7 — Running and configuration
- **FR7.1** One command: `jobscan run --config config/searches.yaml` (exact CLI shape decided in `/design`).
- **FR7.2** Subcommands: `run` (count + collect + fetch details + classify + report), `count` (counts only, fast), `report` (rebuild outputs from stored data), `reclassify` (re-run rules/LLM on stored descriptions).
- **FR7.3** **Resumable:** an interrupted run continues from the last completed slice/page/job; no duplicate requests.
- **FR7.4** All roles, keywords, title patterns, countries, time window, rate limits and LLM on/off live in YAML config, not code.

### FR8 — Outputs
- **FR8.1** A **DuckDB** database file (`data/jobscan.duckdb`), the main store holding every run.
- **FR8.2** CSV/Parquet exports per run: `can_apply.csv` (LATAM-friendly only, with URL and evidence quote), `jobs_all.csv` (every qualified job with label, method, confidence, restriction type, evidence), `counts.csv`, `technologies.csv`.
- **FR8.3** A **Markdown report** per run (`reports/<run_id>.md`): counts funnel per search, eligibility split, top-30 technologies per role and label, the **"can apply" list (LATAM-friendly only)** with links and the quoted evidence sentence for each job, coverage warnings, and an **audit sample** (10 random jobs per label with their evidence) to spot-check. The `UNCLEAR` section appears only with `--include-unclear`. `US_CA_ONLY` jobs appear only as counts and in `jobs_all.csv`, never in the "can apply" list.
- **FR8.4** (Should) A self-contained HTML version of the report with charts.

## 8. Eligibility signals (starting set, extended in config)

| Group | Example phrases (EN / PT / ES) | Effect |
|---|---|---|
| **US/CA restrictive: citizenship / residency** | "US citizen(ship)", "USC", "USC/GC (only)", "GC holders", "green card", "permanent resident", "Canadian citizen or PR", "must reside / be based / live in the US / United States / Canada", "must be located in <state/province list>", "open to residents of <states>", "US persons only", "ITAR / EAR / export-controlled" | Clear restriction → `US_CA_ONLY` (after FR4.2 negation check) |
| **US/CA restrictive: work authorization / visa** | "authorized / eligible / legally able to work in the US / Canada", "work authorization required", "will not / cannot / unable to sponsor", "no (visa) sponsorship", "H-1B", "TN visa", "OPT / CPT", "EAD", "no C2C", "no corp-to-corp", "no third parties", "W-2 only", "T4 employee", "E-Verify", "I-9", "valid SSN / SIN", "security clearance", "public trust" | Clear restriction → `US_CA_ONLY` (after FR4.2 negation check) |
| **US/CA restrictive (PT/ES)** | "somente cidadãos americanos", "necessário visto / autorização de trabalho nos EUA", "residir nos EUA / Canadá", "solo ciudadanos estadounidenses", "residir en EE. UU. / Canadá", "permiso de trabajo en EE. UU." | Clear restriction → `US_CA_ONLY` |
| **LATAM / global positive (hints only)** | "LATAM", "Latin America", "South America", "Brazil", "Brasil", "nearshore", "work from anywhere", "worldwide", "global remote", "any country", "outside the US", "Americas time zones", "international contractor", "Deel / Remote.com / Oyster / EOR", "UTC-3", "aceitamos candidatos do Brasil", "trabajo remoto desde LATAM" | **Never decides on its own.** Passed to the LLM as a hint (FR4.3) |
| **Weak / context-dependent (hints only)** | "remote (US)", "remote – United States", "EST/PST hours", "travel to HQ", "state restrictions apply", "401(k)", "US health / dental / vision", "RRSP", "W-2 benefits", "quarterly onsite" | Passed to the LLM as a hint; the LLM decides whether it implies a restriction |
| **Negation markers** | "not", "no need", "isn't required", "regardless of", "doesn't have to", "cannot", "unable to", "não é necessário", "no es necesario" | Used by FR4.2: a negated restrictive phrase is a hint, not a decision. A negated positive phrase ("not open to candidates outside the US") is a strong restriction hint for the LLM |
| **Stock text** | EEO statements, accommodation paragraphs, benefits text | Scanned for restrictions **first**; only positive phrases inside it are ignored (FR4.6) |

> **Rule:** per the scope, any requirement for US/Canada citizenship, residency, visa or work authorization, **whether stated explicitly or implied** (including "no visa sponsorship", W-2/T4-only employment, state/province lists, US-person rules), makes a job **US_CA_ONLY**, even if it is remote. **LATAM_FRIENDLY requires an explicit statement** quoted from the description.

## 9. Role definitions (config defaults)

| Role | Search keywords | Title pattern (case-insensitive) | Exclude titles |
|---|---|---|---|
| Data Engineer | `data engineer`, `data platform engineer`, `big data engineer`, `ETL engineer` | `\bdata (platform |pipeline )?engineer\b`, `\bbig data engineer\b`, `\betl (developer|engineer)\b`, `\banalytics engineer\b` *(configurable; off by default)* | `manager`, `director` (configurable), `sales` |
| Forward Deployed Engineer | `forward deployed engineer`, `forward deployed software engineer`, `FDE` | `\bforward[- ]deployed\b`, `\bFDE\b` | — |
| AI Engineer | `ai engineer`, `generative ai engineer`, `genai engineer`, `llm engineer`, `applied ai engineer` | `\b(applied |generative |gen ?)?ai engineer\b`, `\bai/ml engineer\b`, `\bml/ai engineer\b`, `\bllm engineer\b`, `\bai (software|platform|solutions) engineer\b` | `sales`, `data annotation`, `AI trainer`, `prompt writer`; pure `machine learning engineer` titles depend on §16.4 AI-Q1 |

**Overlap rule:** one job can match more than one role (e.g. "AI/ML Data Engineer", "Forward Deployed AI Engineer"). It is counted under **each** role it matches, and the overall totals count it **once** (by `job_id`).

## 10. Technology list (starting categories)

| Category | Examples |
|---|---|
| Languages | Python, SQL, Scala, Java, Go (Golang), TypeScript, R, Rust |
| Processing | Spark/PySpark, Flink, Kafka Streams, Beam, Pandas, Polars, DuckDB |
| Orchestration | Airflow, Dagster, Prefect, dbt, Luigi, Argo |
| Warehouses/lakehouse | Snowflake, BigQuery, Redshift, Databricks, Delta Lake, Iceberg, Hudi, Synapse, ClickHouse |
| Streaming/messaging | Kafka, Kinesis, Pub/Sub, RabbitMQ, Event Hubs |
| Cloud | AWS, GCP, Azure (+ services: S3, Glue, EMR, Lambda, Dataflow, Data Factory…) |
| Databases | PostgreSQL, MySQL, MongoDB, DynamoDB, Cassandra, Elasticsearch |
| Infra/DevOps | Docker, Kubernetes, Terraform, CI/CD, GitHub Actions |
| BI | Looker, Tableau, Power BI, Metabase, Superset |
| AI/LLM (FDE + AI Engineer) | LLMs, RAG, agents, LangChain, LangGraph, LlamaIndex, OpenAI / Anthropic / Gemini APIs, Amazon Bedrock, Vertex AI, Azure OpenAI, vector DBs (Pinecone, pgvector, Qdrant, Weaviate, Milvus), embeddings, fine-tuning (LoRA), evals, guardrails, MCP |
| ML / MLOps (AI Engineer) | PyTorch, TensorFlow, scikit-learn, Hugging Face, vLLM, MLflow, Kubeflow, SageMaker, Weights & Biases, ONNX, CUDA |
| Data quality/governance | Great Expectations, Soda, Monte Carlo, Unity Catalog |

Stored as `config/technologies.yaml` with `canonical`, `category`, `aliases[]`, `patterns[]`, `context_required` (optional).

## 11. Data model (logical)

| Table | Key columns |
|---|---|
| `runs` | run_id, started_at, finished_at, config_hash, status, request_count, error_count |
| `searches` | search_id, run_id, role, keywords, country, time_window, filters_json, displayed_count_raw, displayed_count, is_lower_bound |
| `slices` | slice_id, search_id, filters_json, pages_fetched, cards_seen, hit_cap |
| `jobs` | job_id (PK, LinkedIn ID), title, company, company_url, location_text, posted_at, url, first_seen_run, last_seen_run |
| `job_sightings` | job_id, slice_id, run_id |
| `job_details` | job_id, fetched_at, description_text, description_html_gz, seniority, employment_type, job_function, industries, applicants_text, is_closed |
| `classifications` | job_id, run_id, role_matched, remote_status, eligibility_label, confidence, restriction_type, method (rules / llm / rules-fallback), matched_phrases_json, evidence_json, quotes_verified, rules_version, prompt_version, llm_model |
| `technologies` | tech_id, canonical, category |
| `job_technologies` | job_id, tech_id, mention_count, requirement_level |

## 12. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR1 — Politeness | One request at a time by default; random delay of **2–5 s** between requests; exponential backoff on 429 / 999 / 5xx; stop the run after N blocks in a row (configurable). |
| NFR2 — Scale estimate | ~4,500 detail pages (3 roles × 2 countries) × ~3.5 s ≈ **4.5 hours** per full run; `--role` can limit a run to one role; count-only mode in minutes. The report must show the estimate before a full run starts. |
| NFR3 — Resilience | Resumable runs; every page and detail response saved before parsing; fetching and parsing kept separate. |
| NFR4 — Cost | LLM reads every job **not** already excluded by a clear restriction (expected: most jobs); cache by description + prompt-version hash, so a description is classified once across runs; hard cap on LLM calls per run (config). Works with the LLM turned off, but then nothing can be `LATAM_FRIENDLY` (everything not excluded → `UNCLEAR`). The run shows the estimated number of LLM calls before it starts. |
| NFR5 — Reproducibility | Config hash and rules version stored per run; `reclassify` gives the same output for the same inputs. |
| NFR6 — Stack | Python 3.10+, `httpx`, `selectolax` or BeautifulSoup, `pydantic` v2, DuckDB, `typer` CLI, `anthropic` SDK; tests with `pytest` on saved HTML samples. |
| NFR7 — Privacy | No personal data about individuals stored (no recruiter names or profile links); company-level data only. |
| NFR8 — Secrets | `ANTHROPIC_API_KEY` from the environment / `.env`; never committed. |

## 13. Success metrics / acceptance criteria

| ID | Criterion | Target |
|---|---|---|
| AC1 | Count funnel (displayed → collected → role-matched → qualified by label) produced for all 6 searches (3 roles × 2 countries), each role reported separately | 100% |
| AC2 | Coverage on slices whose displayed count is exact (< 1,000) | ≥ 95% of displayed |
| AC3 | Detail fetch success rate | ≥ 98% of role-matched jobs |
| AC4 | **US/CA-only jobs in the "can apply" list**: golden test set (FR4.8) **and** manual audit of 50 random LATAM-friendly jobs | **0** in the golden set; ≤ 2% (≤ 1 of 50) in the audit |
| AC5 | `US_CA_ONLY` recall: golden-set explicit **and** implied restriction cases, plus a manual audit of 50 jobs with restrictive text | 100% golden set; ≥ 95% audit |
| AC5b | Negated/misleading positives ("not open to candidates outside the US", "offices in Brazil") never labelled `LATAM_FRIENDLY` | 100% golden set |
| AC5c | Every `LATAM_FRIENDLY` job has at least one evidence quote that is an exact substring of its description | 100% |
| AC6 | Remote check: hybrid/on-site posts wrongly counted as remote, audit of 50 | ≤ 5% |
| AC7 | Technology extraction recall on the top-50 list, audit of 30 descriptions | ≥ 90% |
| AC8 | Interrupted run resumes with no duplicate detail requests | Verified by test |
| AC9 | Report shows the "can apply" list (LATAM-friendly only) with working links and evidence quotes | Yes |

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LinkedIn ToS forbids automated scraping; IP blocks (HTTP 999/429) | Run fails, IP temporarily blocked | Personal research use only; logged-out pages only; slow request rate; backoff and stop on block; no evasion techniques. Accept that this is a known ToS risk. |
| HTML/endpoint changes | Parsers break | Parsers kept separate with saved HTML test fixtures; raw responses stored for re-parsing; selector change detected → clear error. |
| 1,000-result cap per query | Missed jobs | Adaptive slicing (FR2.2) plus coverage metric and cap warnings (FR1.3). |
| Loose keyword matching inflates counts | Misleading numbers | Displayed count kept as reference only; title pattern decides role (FR1.2). |
| Eligibility is subjective/implicit | A US-only job appears in the "can apply" list | Safe-by-default design (FR4): rules can only exclude; LATAM-friendly needs an explicit, verified quote from the LLM with confidence ≥ 0.8; negation check; restriction scan before stock-text removal; golden test set in CI; audit sample in every report. |
| LLM invents or misreads evidence | Wrong LATAM-friendly label | Quotes must match the description exactly or the label falls to `UNCLEAR` (FR4.4); confidence threshold (FR4.5). |
| Ambiguous tech names (Go, R, Spark) | Inflated counts | Context rules (FR6.3) and audit. |
| Reposted/duplicate jobs under different IDs | Double counting | Secondary duplicate check on (company, normalised title, description hash). |

## 15. Future work (out of v1)
- Scheduled runs and trend charts (data model is already per run).
- Other sources: Indeed (Claude connector available), Wellfound, company ATS pages (Greenhouse/Lever/Ashby APIs), LATAM-focused boards.
- Salary extraction and normalisation (USD/CAD, hourly vs yearly).
- More roles (Analytics Engineer, ML Engineer as its own role, Data Scientist) via config only.
- Dashboard (Streamlit/Evidence) on top of DuckDB.

## 16. Open questions

Each question has a default that will be used if it isn't answered. Role-specific questions are kept in that role's config section.

### 16.1 All roles
| # | Question | Default if unanswered |
|---|---|---|
| G-Q1 | Should `UNCLEAR` jobs appear in the "can apply" list? | **No.** Separate section, hidden by default; `--include-unclear` shows it |
| G-Q2 | Contract-only (1099 / C2C) roles: keep? | Keep and tag the employment type (note: "no C2C" text is still a US/CA restriction, see §8) |
| G-Q3 | Default time window for on-demand runs | Past 30 days |
| G-Q4 | Exclude manager / director-level titles? | Exclude "manager", "director", "head of"; keep "lead", "staff", "principal" |
| G-Q5 | A job that matches two roles: count under both? | Yes under each role, once in overall totals (§9 overlap rule) |

### 16.2 Data Engineer
| # | Question | Default if unanswered |
|---|---|---|
| DE-Q1 | Include **Analytics Engineer** titles? | No (config flag `include_analytics_engineer`) |
| DE-Q2 | Include **ETL developer / BI developer / data warehouse engineer** titles? | ETL developer and data warehouse engineer: yes. BI developer: no |
| DE-Q3 | Include **data platform / data infrastructure / big data** engineer titles? | Yes |
| DE-Q4 | Include **"Software Engineer, Data"** style titles (data in the subtitle)? | Yes, when "data" appears in the title after a comma or dash |
| DE-Q5 | Include **data architect** titles? | No (more senior and design-focused; future role) |

### 16.3 Forward Deployed Engineer
| # | Question | Default if unanswered |
|---|---|---|
| FDE-Q1 | Include close equivalents with other names: **solutions engineer, field engineer, deployment engineer, customer engineer, implementation engineer**? | No. Only titles with "forward deployed" / "FDE". Close equivalents are logged in a review file with their counts, so they can be added later |
| FDE-Q2 | Include **"Forward Deployed AI Engineer"**, **"Forward Deployed Data Engineer"** etc.? | Yes, under FDE **and** the matching role (overlap rule) |
| FDE-Q3 | FDE posts often require **travel to customer sites**. Should "travel required" mark a job as not remote? | No. Travel alone doesn't change remote status. Required travel **inside the US/Canada** goes to the LLM as an implied-restriction hint (§8) |
| FDE-Q4 | FDE posts often mention **customer-facing work in US hours**. Is a time-zone requirement a restriction? | No. Time-zone overlap alone isn't a restriction (US time zones are workable from Brazil); it stays a hint |
| FDE-Q5 | Include **"Forward Deployed" non-engineer** titles (strategist, PM)? | No |

### 16.4 AI Engineer
| # | Question | Default if unanswered |
|---|---|---|
| AI-Q1 | Include pure **Machine Learning Engineer** titles (no "AI" in the title)? | No. Only titles with "AI" / "GenAI" / "LLM". ML Engineer is logged with counts for a future separate role |
| AI-Q2 | Include **"AI/ML Engineer"** combined titles? | Yes |
| AI-Q3 | Include **"Software Engineer (AI)"** / **"Software Engineer, AI Platform"** style titles? | Yes, when "AI" or "LLM" is in the title |
| AI-Q4 | Include **research-oriented** titles (AI research engineer, research scientist)? | Research engineer: yes. Research scientist: no |
| AI-Q5 | Exclude **AI data annotation / AI trainer / prompt writing** gig posts (common remote "AI" listings)? | Yes, excluded by title pattern (§9) |
| AI-Q6 | Split technology rankings into **LLM/GenAI** vs **classic ML/MLOps** for this role? | Yes, using the two categories in §10 |

## 17. Milestones (to be detailed in SDD `/design`)
| # | Milestone | Output |
|---|---|---|
| M1 | Count-only CLI with displayed counts for the 6 searches | `jobscan count` + counts.csv |
| M2 | List collection with adaptive slicing, duplicate removal, DuckDB storage | jobs table, coverage metric |
| M3 | Detail fetch + parsing + raw storage + resume | job_details table |
| M4 | Remote check + restriction scan with negation check + golden test set (FR4.8) + technology extraction | classifications (US_CA_ONLY / pending), job_technologies, passing golden tests for rules |
| M5 | LLM eligibility pass + quote verification + confidence threshold + caching | LATAM_FRIENDLY / UNCLEAR labels, golden set at 0 US-only in "can apply" |
| M6 | Reports (Markdown, optional HTML) + audit sample | reports/<run_id>.md |

## 18. Revision history
| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-31 | First draft from feasibility tests. |
| 1.1 | 2026-10-31 | Eligibility made safe by default: rules can only exclude; LATAM-friendly only from the LLM with an exact quote and confidence ≥ 0.8; implied restrictions covered; negation check; restriction scan before stock-text removal; added US-staffing shorthand (USC/GC, H-1B, TN, OPT, EAD, C2C, E-Verify…); `UNCLEAR` hidden from the "can apply" list; golden test set and zero-leak acceptance criteria. |
| 1.2 | 2026-10-31 | Added **AI Engineer** role (search keywords, title pattern, exclusions, feasibility counts, technology categories); overlap rule for jobs matching several roles; scale estimate updated to 6 searches; open questions split into all-roles / Data Engineer / FDE / AI Engineer. |
