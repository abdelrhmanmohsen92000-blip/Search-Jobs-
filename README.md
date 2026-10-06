# AI Career Hunter — Abdelrhman Mohsen

A Career Intelligence Engine for global BIM Architecture / Interior & Exterior Design job
search, freelance discovery, company targeting, and professional networking. V1.1 turns the
original markdown scaffold into a modular, tested Python system with a CLI, a normalized
opportunity schema, a scoring engine, and generated reports — while preserving every file from
the V1 scaffold (profile, templates, docs, CSVs).

## System architecture

```
career_hunter.py            CLI entrypoint (search / score / companies / networking / daily / weekly / report)

config/
  search_matrix.yaml         Job title families, employment types, regional groups (source of truth for search scope)
  sources.yaml                Source registry, tagged api_source / searchable_source / requires_manual_or_browser_access
  profile_skills.yaml         Machine-readable mirror of profile/profile.md, used by the scoring engine

schemas/
  opportunity.schema.json     JSON Schema every opportunity record is normalized and validated against

scripts/
  lib/                        Shared library code
    paths.py                   Central path constants
    config.py                  YAML loaders + region/title helpers
    scoring.py                  V1.1 weighted scoring engine (8 criteria, 100 pts)
    normalize.py                 Raw -> schema-shaped opportunity + validation
    dedup.py                      Deterministic id + exact/fuzzy deduplication
    storage.py                    CSV/JSON I/O with automatic backup to data/archive/
  search_config.py             Builds the search query plan from config/search_matrix.yaml
  company_intelligence.py      Scores/classifies companies (OPEN_VACANCY / HIDDEN_OPPORTUNITY / LOW_PRIORITY)
  networking_intelligence.py   Scores contacts, maintains tracking/networking.csv, drafts reports/networking_queue.md
  application_intelligence.py  For opportunities scoring >= 80, generates CV/cover-letter/portfolio/interview guidance
  daily_research.py            Orchestrates the full daily pipeline (see below) -> reports/daily_report.md
  weekly_analysis.py           Rolls up tracking/*.csv into reports/weekly_report.md
  score_opportunity.py         Thin CLI wrapper around lib/scoring.py (kept for backward compatibility)

profile/profile.md            Human-readable profile (source of truth for the person; keep in sync with config/profile_skills.yaml)
docs/                         Strategy, scoring, and decision-maker policy documents (prose explanations of the engine)
templates/                    Manual research templates (job/company/contact/outreach) for when a human fills in detail
tracking/                     CSV trackers: jobs, companies, contacts, networking, applications
data/
  raw/                         Drop collected opportunity JSON batches here (see "How to run a research cycle")
  processed/                   Timestamped JSON snapshots of every normalized+scored run
  archive/                     Automatic timestamped backups of any tracking CSV before it's overwritten
reports/                      Generated: daily_report.md, weekly_report.md, networking_queue.md
tests/                        pytest suite covering scoring, dedup, normalization, priority, and malformed/missing data
```

## Installation

```bash
pip install pyyaml jsonschema pytest
```

No other external services are required to run the engine itself (see "What requires
browser/web access" below for what live searching needs).

## Configuration

- **Who I am / what I offer:** `profile/profile.md` (human-readable) and `config/profile_skills.yaml`
  (machine-readable mirror the scoring engine reads). Keep both in sync when the profile changes.
- **What to search for:** `config/search_matrix.yaml` — job title families, employment types,
  regional groups. Titles/regions discovered during real research get appended here.
- **Where to search:** `config/sources.yaml` — every source is tagged `api_source`,
  `searchable_source`, or `requires_manual_or_browser_access` so the engine never assumes
  programmatic access it doesn't have.

## Scoring model (V1.1)

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

Each sub-score is 0–10; `scripts/lib/scoring.score_opportunity_record()` returns
`score, priority, recommendation, matched_skills, missing_skills, strengths, risks`.
Priority bands: EXCEPTIONAL (90+), STRONG (75+), GOOD (60+), MODERATE (40+), LOW (<40).
A company with no public vacancy is never scored LOW by default — see `HIDDEN_OPPORTUNITY`
in `scripts/company_intelligence.py`.

## CSV / tracker structure

| File | Purpose |
|---|---|
| `tracking/jobs.csv` | Every normalized, scored job opportunity (see `schemas/opportunity.schema.json`) |
| `tracking/companies.csv` | Every researched company, with `category` = `OPEN_VACANCY` / `HIDDEN_OPPORTUNITY` / `LOW_PRIORITY` and `ai_fit_score` |
| `tracking/contacts.csv` | Original V1 per-contact tracker (kept for manual research notes) |
| `tracking/networking.csv` | V1.1 networking engine output — `network_value_score`, priority (A/B/C), connection/message status |
| `tracking/applications.csv` | Application + interview pipeline, read by `weekly_analysis.py` |

Every write to a tracker is preceded by an automatic timestamped backup into `data/archive/` —
no research cycle can silently destroy prior data.

## How to run a research cycle

The engine (query generation, normalization, dedup, scoring, reporting) runs without any
network access. Collecting real postings/companies/contacts from the live web does need
browser or API access that this environment does not have — see below. The actual research
step is where a human, or an agent session with web access, supplies the facts.

1. Drop one or more JSON files into `data/raw/` — each a list of loosely-shaped opportunity
   dicts (see `schemas/opportunity.schema.json` for fields; include an optional `_sub_scores`
   dict with the 8 scoring criteria, each 0–10, if you've already assessed the posting).
2. Run a cycle:
   ```bash
   python career_hunter.py daily --region gulf
   python career_hunter.py daily --remote
   python career_hunter.py daily --freelance
   python career_hunter.py daily                 # all regions
   ```
   This normalizes, deduplicates, scores, appends to `tracking/jobs.csv`, and writes
   `reports/daily_report.md` with TOP 10 OPPORTUNITIES, HIDDEN OPPORTUNITIES, NETWORKING
   TARGETS, and FOLLOW-UPS.
3. Log companies and contacts as they're researched:
   ```bash
   python career_hunter.py companies --from-json path/to/company.json
   python career_hunter.py companies --list-hidden
   python career_hunter.py networking --from-json path/to/contact.json --generate-queue
   ```
4. Weekly rollup:
   ```bash
   python career_hunter.py weekly
   ```
   Writes `reports/weekly_report.md`: pipeline stats, best markets/titles/sources/companies/
   networking channels, and recommended strategy changes, derived entirely from logged data.
5. `python career_hunter.py search --region europe|gulf|... | --remote | --freelance` shows
   the query plan (titles × employment types × regions × sources) a research session should
   execute — this is the SEARCH ENGINE IMPLEMENTATION, not a LIVE SEARCH EXECUTION.
6. For any opportunity that scores ≥80, generate an application plan (never inventing
   experience):
   ```bash
   python scripts/application_intelligence.py data/processed/<snapshot>.json
   ```

## What requires browser/web access

This sandboxed environment cannot reach job boards, company sites, or LinkedIn. To make a
cycle fully live rather than scaffold-driven, run the collection step in a session with:
- Outbound HTTPS/browser access to the sources listed in `config/sources.yaml`.
- For `requires_manual_or_browser_access` sources (LinkedIn, Glassdoor, Upwork): a logged-in,
  human-controlled browser session — never automated scraping or login bypass.
- For `api_source` entries (Remote OK, Remotive): their public JSON endpoints, no key needed.

Whatever that session collects should be saved as JSON into `data/raw/` in the shape described
above, then `python career_hunter.py daily` picks it up. `reports/daily_report.md` always
states plainly whether a cycle's "Execution mode" was a live batch or "NOT PERFORMED" — this
system never fabricates search results.

## LinkedIn / human-approval policy

No LinkedIn automation of any kind: no scraping at scale, no auto-connect, auto-message,
auto-like, or auto-comment, and no circumventing platform restrictions. `networking_intelligence.py`
only scores contacts and drafts outreach into `reports/networking_queue.md` (WHO / WHY / WHAT TO
SAY / WHEN / LINK) and `templates/outreach-message.md`. Every LinkedIn connection request and
message is reviewed and sent manually by Abdelrhman.

## Tests

```bash
python -m pytest tests/ -q
```
Covers scoring (weights, bands, skill-gap), deduplication (exact + fuzzy), normalization
(defaults, coercion, region resolution, schema validation), priority/classification logic
(company categories, networking priority bands), and resilience to missing/malformed input
(empty records, wrong types, missing required fields never crash the pipeline).
