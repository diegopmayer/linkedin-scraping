# jobscan

On-demand command-line tool that answers one question:

> How many remote US/Canada **Data Engineer**, **Forward Deployed Engineer** and **AI Engineer** jobs on LinkedIn could a candidate living in Brazil apply to right now, and which technologies do they ask for?

It counts and collects jobs from LinkedIn's public (logged-out) job pages, opens each matching post, decides whether the company **explicitly** accepts candidates from LATAM / Brazil / worldwide, and ranks the tools mentioned.

Requirements and design: `docs/prd/PRD-001-linkedin-remote-job-market.md`, `.claude/sdd/features/DEFINE_LINKEDIN_REMOTE_JOB_SCANNER.md`, `.claude/sdd/features/DESIGN_LINKEDIN_REMOTE_JOB_SCANNER.md`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # then put your Anthropic API key in .env
```

The AI step uses Claude Haiku (`claude-haiku-5-5`) through the `anthropic` SDK. It reads `ANTHROPIC_API_KEY` from the environment or `.env`. Without a key the tool still runs, but no job can be labelled LATAM-friendly (see "Safety rules").

## Commands

```bash
jobscan count                         # LinkedIn's displayed count for each search (6 requests)
jobscan run --dry-run                 # counts + a rough time/request/cost estimate
jobscan run                           # full run: collect, open posts, classify, report
jobscan run --role data_engineer --country Canada   # smaller run
jobscan run --resume                  # continue a paused or failed run
jobscan report --include-unclear      # rebuild the report from stored data, listing unclear jobs too
jobscan reclassify                    # classify stored posts again after changing rules or the prompt
```

Role ids: `data_engineer`, `forward_deployed_engineer`, `ai_engineer`. Countries: `United States`, `Canada`.

Exit codes: `0` done, `2` config error, `3` paused after repeated blocking (run `--resume` later), `4` LinkedIn markup changed or data-quality gate failed, `5` another `jobscan` process is running, `130` interrupted (resumable).

## Outputs

Each run writes `reports/<run_id>/`:

| File | Contents |
|---|---|
| `report.md` | Count funnel per role and country, coverage warnings, the **can-apply list** with quoted evidence, technology rankings, classification method split, audit sample |
| `can_apply.csv` | LATAM-friendly jobs only, with link and evidence sentence |
| `jobs_all.csv` | Every qualified job with its label, method, confidence, restriction type and evidence |
| `counts.csv` | The funnel: displayed → collected → title-matched → qualified (LATAM-friendly / unclear / US-CA-only) |
| `technologies.csv` | Top technologies overall, by role, by eligibility label and by country |
| `review/audit_sample.csv` | Random jobs per label to check by hand |
| `review/role_boundary.csv` | Titles close to a role that were not counted (e.g. "Machine Learning Engineer") |
| `review/unknown_terms.csv` | Frequent tech-looking terms that are not in `config/technologies.yaml` |

All data lives in `data/jobscan.duckdb` (raw pages, jobs, details, labels, LLM cache). Query it directly with DuckDB if you want, e.g. `SELECT * FROM v_funnel`.

## How the counts work

- **Displayed** is LinkedIn's banner. It is capped ("11,000+") and matches keywords loosely, so it's only a reference.
- **Collected** are unique jobs reached. LinkedIn shows at most 1,000 results per search, so big searches are split by experience level, then job type, then two sort orders. The search itself is collected first, so jobs without a seniority level are not lost. Searches that still hit the limit are listed in the report.
- **Title-matched** jobs fit a role's title patterns in `config/searches.yaml` (one job can count under several roles; totals count it once).
- **Qualified** jobs are title-matched, open, and remote (or not stated). Hybrid and on-site jobs are left out.

## Safety rules for eligibility

A mistake should only cost you a job you could have applied to; it must never put a job you can't apply to in your list.

1. Phrase rules (`config/eligibility_rules.yaml`) scan the full description first. A clear restriction (US citizen, green card, "authorized to work in the US", no sponsorship, USC/GC, W-2 only, clearance, state lists…) labels the job **US/CA-only**. Negated phrases ("you don't need to be a US citizen") don't count as restrictions.
2. Every other job goes to Claude Haiku with the instructions in `src/jobscan/prompts/eligibility_v1.md`. It labels a job US/CA-only when a restriction is stated **or implied** (US-only payroll/benefits, required office visits, state lists, SSN checks).
3. **LATAM-friendly** needs an explicit statement. The model must quote it, the quote must appear word for word in the description, and its confidence must be ≥ 0.8. Otherwise the job is **unclear**. A database constraint enforces this too.
4. If the AI is off, out of budget, refuses or fails, the job is **unclear**, never LATAM-friendly.
5. Unclear jobs are hidden from the report unless you pass `--include-unclear`.

## Configuration

- `config/searches.yaml`: roles (keywords, title include/exclude/boundary patterns), countries, time window (`r2592000` = past 30 days), slicing, request rate, LLM, report options.
- `config/technologies.yaml`: the technology list (canonical name, category, aliases, regex patterns, context rules).
- `config/eligibility_rules.yaml`, `config/remote_rules.yaml`: phrase rules; bump `rules_version` when you change them, then run `jobscan reclassify`.

## Tests

```bash
.venv/bin/pytest                    # unit, integration and offline golden tests (no network)
.venv/bin/pytest -m llm tests/golden   # golden eligibility set through the real API (needs a key)
.venv/bin/pytest -m live            # 3 real LinkedIn requests to detect markup changes
```

`tests/golden/cases.yaml` currently holds synthetic cases. Add at least 30 real descriptions from your runs, labelled by hand (`synthetic: false`), before relying on the AI step.

## Request rate and LinkedIn's terms

The tool makes one request at a time with a random 2–5 second pause, backs off on HTTP 429/999/5xx, and stops after 5 blocking responses in a row (resume later). It uses only logged-out pages: no account, no cookies, no proxies, no CAPTCHA solving. LinkedIn's terms don't allow automated collection; this tool is for personal research at a low rate, and you accept that risk by running it. It stores company-level data only, never people's profiles.

A first full run (all roles, both countries) takes several hours, mostly opening job pages. Later runs reuse stored pages and AI answers, so they are much faster.
