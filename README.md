# AI Career Hunter — Abdelrhman Mohsen

A Career Intelligence Engine for global BIM Architecture / Interior & Exterior Design job
search, freelance discovery, company targeting, and professional networking.

- **V1.1** turned the original markdown scaffold into a modular, tested Python system: a CLI, a
  normalized opportunity schema, a scoring engine, and generated reports.
- **V1.2** turns that framework into a **live research engine**: real source adapters (Remote OK
  and Remotive make genuine HTTP calls), a source-health-aware pipeline that never fails
  completely because one source is down, global/regional/remote/freelance query generation, and
  richer company/networking/application intelligence wired into one daily cycle.

Every file from V1.0/V1.1 (profile, templates, docs, CSVs) is preserved.

## System architecture

```
career_hunter.py            CLI entrypoint (search / score / companies / networking / applications / daily / weekly / report)

config/
  search_matrix.yaml         Job title families, employment types, regional groups (global coverage, no fixed-country assumption)
  sources.yaml                Source registry: access_method (API / PUBLIC_WEB / BROWSER_REQUIRED / MANUAL), coverage, reliability, enabled
  profile_skills.yaml         Machine-readable mirror of profile/profile.md, used by the scoring engine

schemas/
  opportunity.schema.json     JSON Schema every opportunity record is normalized and validated against

scripts/
  lib/                        Shared library code
    paths.py                   Central path constants
    config.py                  YAML loaders + region/title helpers
    scoring.py                  V1.1 weighted scoring engine (8 criteria, 100 pts) + ACTION classifier
    normalize.py                 Raw -> schema-shaped opportunity + validation
    dedup.py                      Deterministic id + exact/fuzzy deduplication
    storage.py                    CSV/JSON I/O with automatic backup to data/archive/
  sources/                    Source-adapter architecture (V1.2) — see "Sources" below
    base.py                     SourceAdapter interface, SourceRunResult, HTTP helpers (timeout+retry, never fabricates on failure)
    remoteok.py                  LIVE: Remote OK public JSON API
    remotive.py                  LIVE: Remotive public JSON API
    manual_import.py             Reads human/browser-session-collected batches from data/raw/*.json
    generic_search.py            PUBLIC_WEB boards: fetches raw HTML only (no parser yet — see "How to add a new source")
    company_careers.py           Per-company careers-page fetch (same raw-HTML-only honesty constraint)
  search_config.py             Builds the search query plan; rank_regions() orders regions by logged outcomes, never a fixed "Gulf first"
  company_intelligence.py      Scores/classifies companies (OPEN_VACANCY / HIDDEN_OPPORTUNITY / LOW_PRIORITY)
  networking_intelligence.py   Scores contacts, maintains tracking/networking.csv, drafts reports/networking_queue.md
  application_intelligence.py  For opportunities scoring >= 80, generates CV/cover-letter/portfolio/interview guidance
  daily_research.py            Orchestrates the full live pipeline (see below) -> reports/daily_report.md
  weekly_analysis.py           Rolls up tracking/*.csv into reports/weekly_report.md + reports/weekly_strategy.md
  score_opportunity.py         Thin CLI wrapper around lib/scoring.py (kept for backward compatibility)

profile/profile.md            Human-readable profile (source of truth for the person; keep in sync with config/profile_skills.yaml)
docs/                         Strategy, scoring, and decision-maker policy documents (prose explanations of the engine)
templates/                    Manual research templates (job/company/contact/outreach) for when a human fills in detail
tracking/                     CSV trackers: jobs, companies, contacts, networking, applications
data/
  raw/                         Drop collected opportunity JSON batches here (Manual Import adapter reads *.json at the top level)
  processed/                   Timestamped JSON snapshots of every normalized+scored run, and of application plans
  archive/                     Automatic timestamped backups of any tracking CSV before it's overwritten
reports/                      Generated: daily_report.md, weekly_report.md, weekly_strategy.md, networking_queue.md
tests/                        pytest suite: scoring, dedup, normalization, priority, malformed/missing data, sources, pipeline, applications
```

## Installation

```bash
pip install pyyaml jsonschema pytest
```

No API keys are required for the two live sources (Remote OK, Remotive are public, unauthenticated
JSON feeds). See "Sources" below for what each source actually needs.

## Configuration

- **Who I am / what I offer:** `profile/profile.md` (human-readable) and `config/profile_skills.yaml`
  (machine-readable mirror the scoring engine reads). Keep both in sync when the profile changes.
- **What to search for:** `config/search_matrix.yaml` — job title families, employment types,
  and regional groups covering Gulf/Middle East, Europe, UK, North America, Oceania, Asia,
  Africa, and worldwide remote. Titles/regions discovered during real research get appended here.
  `--region global` (or `worldwide`/`all`) searches every region; no region is ever assumed best —
  `search_config.rank_regions()` orders them by logged outcomes in `tracking/jobs.csv` once data exists.
- **Where to search:** `config/sources.yaml` — every source declares `access_method`
  (`API` / `PUBLIC_WEB` / `BROWSER_REQUIRED` / `MANUAL`), `requires_login`, `requires_browser`,
  `api_available`, `country_coverage`, `job_types`, `reliability`, and `enabled`, so the engine
  never assumes access it doesn't have.

## Sources

| Source | access_method | Status in this environment | Notes |
|---|---|---|---|
| Remote OK | API | **LIVE** (adapter implemented) | Public JSON feed, no key. Blocked here by this sandbox's network policy — see below. |
| Remotive | API | **LIVE** (adapter implemented) | Public JSON feed, no key. Same network-policy block here. |
| Manual Import | MANUAL | **LIVE** | Reads `data/raw/*.json` — the integration point for any browser-session or human-collected batch. |
| Indeed, Bayt, GulfTalent, Naukrigulf, Wellfound, ArchDaily, We Work Remotely, Contra, Fiverr, Freelancer.com, PeoplePerHour, Reddit, AUGI | PUBLIC_WEB | Adapter fetches raw HTML only | No parser is wired up yet (Phase: "How to add a new source" below) — this is a deliberate boundary, not a bug. |
| LinkedIn Jobs, Glassdoor, Upwork | BROWSER_REQUIRED | Never automated | `enabled: false` in `config/sources.yaml`. Results only ever arrive via a human-controlled browser session, fed in through Manual Import. |

**Why "LIVE" sources show UNAVAILABLE when you actually run this**: this sandboxed environment's
outbound network policy blocks `remoteok.com` and `remotive.com` (`403 Forbidden` at the egress
proxy — confirmed, not assumed). The adapters are fully implemented with real `urllib` HTTP
calls, a 10s timeout, and 2 retries with backoff; in an environment whose network policy allows
these two hosts, `python career_hunter.py daily` returns real postings with no code changes.
`reports/daily_report.md`'s SOURCE HEALTH table always shows the literal error, never a guess.

## Scoring model (V1.1, unchanged in V1.2)

8 criteria, 100 points total — see `docs/scoring-model.md` for full detail:

| Criterion | Weight |
|---|---|
| Technical Match | 25 |
| Experience Match | 20 |
| Software Match | 15 |
| Project Match | 10 |
| Location / Work Mode | 10 |
| Eligibility | 10 |
| Career Value | 5 |
| Compensation Potential | 5 |

Each sub-score is 0–10; `scripts/lib/scoring.score_opportunity_record()` returns `score, priority,
recommendation, action, matched_skills, missing_skills, strengths, risks`, plus the 8 individual
sub-scores. Priority bands: EXCEPTIONAL (90+), STRONG (75+), GOOD (60+), MODERATE (40+), LOW (<40).
`action` is `APPLY_NOW` / `APPLY` / `CONSIDER` / `NETWORK_FIRST` (decent score but weak eligibility)
/ `LOW_PRIORITY` / `SKIP`. A company with no public vacancy is never scored LOW by default — see
`HIDDEN_OPPORTUNITY` in `scripts/company_intelligence.py`.

## Company intelligence

`scripts/company_intelligence.py` classifies every researched company as `OPEN_VACANCY`,
`HIDDEN_OPPORTUNITY` (strong BIM/hiring signal, no public vacancy — never excluded for lacking
one), or `LOW_PRIORITY`, with an `ai_fit_score` (0–100) from BIM activity, hiring activity,
relevant titles, project-type overlap with the profile, and web presence.

## Networking intelligence

`scripts/networking_intelligence.py` scores contacts 0–100 (`network_value_score`) from role
authority (Founder/Director/BIM Manager rank highest), BIM/architecture relevance, company fit,
geographic relevance, and career value, then writes `reports/networking_queue.md`: WHO / WHY /
WHAT TO SAY / WHEN / LINK / **Suggested Action** per contact. The suggested action is always a
step for a human to perform — see LinkedIn policy below.

## Application intelligence

For every opportunity scoring **≥ 80**, `scripts/application_intelligence.py` (run automatically
by `daily_research.py`, saved to `data/processed/application_plans.<timestamp>.json`) generates
recommended CV changes, cover-letter requirements, a portfolio recommendation, an email strategy,
a LinkedIn strategy, and interview-prep topics — all derived only from `config/profile_skills.yaml`
and the posting's matched/missing skills. It never invents experience, software, or qualifications;
missing skills are explicitly flagged as "do not claim."

## CSV / tracker structure

| File | Purpose |
|---|---|
| `tracking/jobs.csv` | Every normalized, scored job opportunity (see `schemas/opportunity.schema.json`), including `action` |
| `tracking/companies.csv` | Every researched company, with `category` = `OPEN_VACANCY` / `HIDDEN_OPPORTUNITY` / `LOW_PRIORITY` and `ai_fit_score` |
| `tracking/contacts.csv` | Original V1 per-contact tracker (kept for manual research notes) |
| `tracking/networking.csv` | Networking engine output — `network_value_score`, priority (A/B/C), connection/message status |
| `tracking/applications.csv` | Application pipeline: `opportunity_id, company, job_title, country, source, url, score, cv_version, portfolio_version, application_date, status, contact_person, linkedin, email, follow_up_date, interview_date, result, reason, notes`. `status` ∈ `NEW, REVIEW, READY_TO_APPLY, APPLIED, FOLLOW_UP, INTERVIEW, OFFER, ACCEPTED, REJECTED, CLOSED`. |

Every write to a tracker is preceded by an automatic timestamped backup into `data/archive/` —
no research cycle can silently destroy prior data.

## How to run a research cycle

1. **Live sources run automatically** — no setup needed. `python career_hunter.py daily --region <key>`
   calls Remote OK and Remotive for real; whatever they return is normalized, deduplicated, scored,
   and ranked. If a host is blocked (as in this sandbox) or down, that source reports UNAVAILABLE
   with the real error and the cycle continues with everything else — see SOURCE HEALTH in the report.
2. For any other board (PUBLIC_WEB or BROWSER_REQUIRED), collect postings in a session with the
   right access and drop them as JSON into `data/raw/` — the Manual Import adapter picks them up
   automatically on the next cycle (see `schemas/opportunity.schema.json` for fields; include an
   optional `_sub_scores` dict with the 8 scoring criteria, each 0–10, if you've already assessed it).
3. Run a cycle:
   ```bash
   python career_hunter.py daily --region gulf
   python career_hunter.py daily --region global
   python career_hunter.py daily --remote
   python career_hunter.py daily --freelance
   python career_hunter.py daily --source "Remote OK" --limit 20
   python career_hunter.py daily --region global --dry-run   # preview only, touches nothing
   ```
   This runs every enabled adapter, validates/normalizes/deduplicates/scores/ranks the results,
   appends to `tracking/jobs.csv`, generates application plans for score ≥ 80, and writes
   `reports/daily_report.md` (Executive Summary, TOP OPPORTUNITIES, HIDDEN OPPORTUNITIES,
   FREELANCE, NETWORKING, FOLLOW UPS, MARKET INTELLIGENCE, SOURCE HEALTH) plus
   `reports/networking_queue.md`.
4. Log companies and contacts as they're researched:
   ```bash
   python career_hunter.py companies --from-json path/to/company.json
   python career_hunter.py companies --list-hidden
   python career_hunter.py networking --from-json path/to/contact.json --generate-queue
   python career_hunter.py applications --list-pending
   ```
5. Weekly rollup:
   ```bash
   python career_hunter.py weekly
   ```
   Writes `reports/weekly_report.md` (pipeline stats, best markets/titles/sources/companies/
   networking channels) and `reports/weekly_strategy.md` (the 10 strategy questions — strongest
   countries, highest-matching titles, repeat companies, best platforms, response/rejection
   rates, working networking actions, repeated skill gaps, best CV version, concrete next-week
   changes), all derived from logged data only.
6. `python career_hunter.py search --region europe|gulf|north_america|...|global --remote --freelance --dry-run`
   shows the query plan and geographic coverage without touching any file.

## Dry run

`--dry-run` on `search` or `daily` generates the query plan, shows enabled sources, geographic
coverage, and expected search volume, and modifies **nothing** — no tracker writes, no reports,
no fabricated opportunities:
```bash
python career_hunter.py search --region global --dry-run
python career_hunter.py daily --region global --dry-run
```

## How to add a new source

1. Create `scripts/sources/<name>.py` implementing `SourceAdapter` (see `scripts/sources/base.py`):
   a `fetch(query=None, limit=None)` method returning a `SourceRunResult` with real `opportunities`
   on success, or `status="UNAVAILABLE"`/`"ERROR"` and no fabricated data on failure.
2. If it's a documented API, use `base.http_get_json()` (timeout + retry built in), following
   `remoteok.py`/`remotive.py` as a template.
3. If it's PUBLIC_WEB with no API, start from `generic_search.py`'s raw-HTML-fetch pattern and
   add an HTML parser for that board's result markup (the one piece deliberately left as a stub
   in V1.2 — see "Sources" above).
4. Register an instance in `scripts/sources/__init__.py`'s `REGISTRY` and add its metadata to
   `config/sources.yaml`. Nothing in `scripts/daily_research.py` or the scoring engine needs to change.
5. For a BROWSER_REQUIRED source (LinkedIn, Glassdoor, Upwork), never write a scraper — collect
   results in a human-controlled logged-in session and feed them in as a `data/raw/*.json` batch
   through the existing Manual Import adapter instead.

## LinkedIn / human-approval policy

No LinkedIn automation of any kind: no scraping at scale, no auto-connect, auto-message,
auto-like, or auto-comment, no bypassing restrictions, no bulk actions. The system's role stops
at RESEARCH → IDENTIFY → SCORE → PREPARE → ASK HUMAN TO ACT → TRACK RESULT.
`networking_intelligence.py` only scores contacts and drafts outreach into
`reports/networking_queue.md` (WHO / WHY / WHAT TO SAY / WHEN / LINK / Suggested Action) and
`templates/outreach-message.md`. Every LinkedIn connection request and message is reviewed and
sent manually by Abdelrhman; only the outcome is tracked back into `tracking/networking.csv`.

## Limitations (stated plainly, not glossed over)

- This sandboxed environment's egress policy blocks the two live API hosts (Remote OK, Remotive)
  with a `403` at the proxy — confirmed via direct test, not assumed. The adapters are fully
  implemented and will return real data unmodified in an environment that allows those hosts.
- PUBLIC_WEB boards (Indeed, Bayt, etc.) have no documented API; their adapters fetch raw HTML
  only — no results are extracted until a parser is written per board (see "How to add a new
  source"). This is intentional: inventing structured postings from unparsed HTML would mean
  fabricating data, which this system refuses to do.
- BROWSER_REQUIRED sources are never touched programmatically, by design, not by capability gap.
- `rank_regions()` needs logged `tracking/jobs.csv` data to actually rank; with none yet, regions
  are returned in config order (not a ranking, just a stable default) — see `search_config.py`.

## Tests

```bash
python -m pytest tests/ -q
```
Covers scoring (weights, bands, skill-gap, ACTION classification), deduplication (exact + fuzzy),
normalization (defaults, coercion, region resolution, schema validation), priority/classification
logic (company categories, networking priority bands, hidden-opportunity detection), application
plan generation (never claims a missing skill), resilience to missing/malformed input (empty
records, wrong types, missing required fields are rejected with a reason, never silently
discarded or crashed on), and the V1.2 live-research layer: source-adapter success/failure/
malformed-response handling (via monkeypatched HTTP, so tests never depend on network access),
global/regional/remote/freelance query generation, source-health recording, and dry-run behavior
(touches no trackers, produces no fake data).
