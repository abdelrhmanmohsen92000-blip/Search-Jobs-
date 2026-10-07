# AI Career Hunter — Abdelrhman Mohsen

A Career Intelligence Engine for global BIM Architecture / Interior & Exterior Design job
search, freelance discovery, company targeting, and professional networking.

- **V1.1** turned the original markdown scaffold into a modular, tested Python system: a CLI, a
  normalized opportunity schema, a scoring engine, and generated reports.
- **V1.2** turns that framework into a **live research engine**: real source adapters (Remote OK
  and Remotive make genuine HTTP calls), a source-health-aware pipeline that never fails
  completely because one source is down, global/regional/remote/freelance query generation, and
  richer company/networking/application intelligence wired into one daily cycle.
- **V1.3** adds the **Web Intelligence Layer**: turning real web-search results (collected by a
  human or a browser-capable session) into structured, scored opportunities — source routing,
  HTML extraction, rule-based job/freelance/company-signal classification, provenance,
  confidence scoring, stale-opportunity detection, source-preserving deduplication, and company
  entity resolution. See "Web Intelligence Layer" below.
- **V1.4** adds the **AI Intelligence Engine** — the final layer, turning the pipeline into a
  practical decision tool: a provider-agnostic AI interface (rule-based by default, no API key
  required), job fit/quality/risk analysis kept separate from the V1.1 `match_score`, a decision
  engine (APPLY_NOW/APPLY/NETWORK_FIRST/RESEARCH_COMPANY/CONSIDER/LOW_PRIORITY/SKIP, always with a
  reason), skill-gap and learning-priority analysis, company grading (A+ to D), a CV change plan,
  tiered AI cost control, alerts, and decision history. See "AI Intelligence Engine" below. After
  V1.4, version numbers stop incrementing for routine work — only a genuine architectural change
  gets a new number.

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
  web_research.py              V1.3 Web Intelligence Layer orchestrator (web-import pipeline) -> tracking/jobs.csv, reports
  web/                         Web Intelligence Layer (V1.3) — see "Web Intelligence Layer" below
    base.py                     SearchResult / SearchProviderResult / WebSearchProvider / PageExtractionResult types
    source_router.py             Identifies a source from a URL/domain (LinkedIn, Indeed, ..., Company Career Page, Unknown)
    page_extractor.py            Stdlib-only HTML -> title/headings/links/job-fields extraction; JS_REQUIRED detection
    opportunity_extractor.py     Search result/page -> candidate opportunity + OPEN_VACANCY/FREELANCE_PROJECT/COMPANY_SIGNAL/IRRELEVANT classifier
    manual_search_import.py      Reads data/raw/search_results/*.json; also a WebSearchProvider implementation
    search_engine.py              Ties query plan to a WebSearchProvider; reports SEARCH_PROVIDER_UNAVAILABLE honestly
    browser_queue.py              Generates reports/browser_search_queue.md for BROWSER_REQUIRED/PUBLIC_WEB sources
  career_intelligence.py       V1.4 full pipeline orchestrator: LOAD->ANALYZE->DECIDE->NETWORK->APPLY->REPORT->LEARN
  intelligence/                 AI Intelligence Engine (V1.4) — see "AI Intelligence Engine" below
    ai_provider.py               AIProvider interface; RuleBasedAIProvider (default, no API key); tier_for_score() cost control
    job_analyzer.py               fit_score / quality_score / risk_score / ai_opportunity_score — separate from match_score
    skill_gap.py                   MATCH/PARTIAL_MATCH/MISSING/UNKNOWN classification + frequency-backed learning priority
    decision_engine.py             APPLY_NOW/APPLY/NETWORK_FIRST/RESEARCH_COMPANY/CONSIDER/LOW_PRIORITY/SKIP + why/risks/next_action + action_priority
    company_analyzer.py            COMPANY_PRIORITY (A+ to D) + honestly-UNKNOWN-gapped company analysis
    cv_strategy.py                  CV_CHANGE_PLAN (headline/skills/experience/projects/portfolio) — never rewrites or invents
    application_strategy.py         Wraps application_intelligence.py; HIGH-VALUE flag (score>=90); portfolio_recommendation()
    career_strategy.py              Best countries/titles/companies/sources/work-modes + market_intelligence() (sample-sized)
    learning_engine.py              Response/interview/offer/networking rates by segment, always with sample_size

profile/profile.md            Human-readable profile (source of truth for the person; keep in sync with config/profile_skills.yaml)
docs/                         Strategy, scoring, and decision-maker policy documents (prose explanations of the engine)
                               docs/PRODUCTION_READINESS.md — component-by-component readiness audit, data-flow
                               findings, real Claude/web-search integration requirements, and next steps
templates/                    Manual research templates (job/company/contact/outreach) for when a human fills in detail
tracking/                     CSV trackers: jobs, companies, contacts, networking, applications, decisions, skill_gaps, learning, alerts
data/
  raw/                         Drop collected opportunity JSON batches here (Manual Import adapter reads *.json at the top level)
  raw/search_results/           V1.3: drop web-search-result JSON batches here for `web-import` (see "Manual search import")
  processed/                   Timestamped JSON snapshots of every normalized+scored run, and of application plans
  archive/                     Automatic timestamped backups of any tracking CSV before it's overwritten
  alerts/                       V1.4: timestamped JSON snapshots of every alerts batch (data/alerts/*.json)
reports/                      Generated: daily_report.md (CAREER COMMAND REPORT, V1.4), weekly_report.md, weekly_strategy.md,
                               networking_queue.md, browser_search_queue.md, alerts.md
tests/                        pytest suite: scoring, dedup, normalization, priority, malformed/missing data, sources, pipeline,
                               applications, AI intelligence engine
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
- **AI provider:** `config/ai.yaml` — `provider: rule_based` by default (no API key needed to run
  or test the repository), plus placeholder configs for `openai`/`claude`/`local_llm` and the
  score thresholds for tiered AI analysis. See "AI Intelligence Engine" below.

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

## Web Intelligence Layer (V1.3)

Converts real web-search results into structured, scored opportunities:

```
WEB SEARCH -> SEARCH RESULT COLLECTION -> RESULT EXTRACTION -> SOURCE IDENTIFICATION ->
CONTENT EXTRACTION -> OPPORTUNITY EXTRACTION -> NORMALIZATION -> DEDUPLICATION -> SCORING ->
COMPANY INTELLIGENCE -> NETWORKING -> APPLICATION INTELLIGENCE -> REPORT
```

It reuses the existing scoring/normalization/storage/reporting architecture (`scripts/lib/*`,
`company_intelligence.py`) rather than duplicating it — `scripts/web_research.py` is the thin
orchestrator that wires the two together.

**Search providers** (`scripts/web/base.py: WebSearchProvider`): a generic `search(query, limit)`
interface so the system never hardcodes one provider. Only `ManualSearchImportProvider`
(`scripts/web/manual_search_import.py`) is wired up today — it reads human/browser-collected
batches from `data/raw/search_results/*.json`:
```json
[
  {"title": "BIM Architect", "url": "https://example.com/job/123",
   "snippet": "Looking for a BIM Architect with Revit experience...",
   "source": "search_engine", "query": "BIM Architect Revit Germany", "region": "europe"}
]
```
No missing field is ever invented — absent values stay `null`/empty exactly as in the input.

**Source routing** (`scripts/web/source_router.py`): identifies LinkedIn, Indeed, Bayt,
GulfTalent, Naukrigulf, Glassdoor, Wellfound, Remote OK, Remotive, We Work Remotely, Contra,
Upwork, Freelancer, PeoplePerHour, Fiverr, a generic Company Career Page, or `Unknown` from a
URL/domain, with `requires_browser` and a `confidence` that is `1.0` for a known domain, a
heuristic `0.5` for a plausible careers-page guess, and `0.0` for anything unrecognized — never
asserted as a known source without evidence.

**Page extraction** (`scripts/web/page_extractor.py`): stdlib-only HTML parsing (no JS
rendering) for title, visible text, headings, links, and best-effort job-posting fields
(company — only from structured markup, never guessed from free text at the page level —
job title, location, employment type, remote, salary, skills, application URL). A page that
looks JS-rendered (SPA shell, near-empty body) reports `PAGE_STATUS = JS_REQUIRED` instead of
extracting nothing and pretending it's complete.

**Opportunity extraction & classification** (`scripts/web/opportunity_extractor.py`): converts a
search result (+ optional page extraction) into a candidate matching
`schemas/opportunity.schema.json`, and classifies it `OPEN_VACANCY` / `FREELANCE_PROJECT` /
`COMPANY_SIGNAL` / `IRRELEVANT` with a rule-based (no external AI dependency) classifier. A
company name is only filled in when a specific textual pattern supports it ("X is hiring",
"join X", page markup) — otherwise it's left empty and the record is rejected downstream with a
reason, never fabricated. `COMPANY_SIGNAL` results never become a job opportunity — they route
into `company_intelligence.py` as a `HIDDEN_OPPORTUNITY` candidate instead (same classification
rules as V1.2, now fed by web signals too).

**Provenance & confidence** (schema fields `provenance` / `confidence_score`): every web-derived
opportunity carries `{source, source_url, search_query, retrieved_at, extraction_method,
confidence}` — we always know where a job came from. `confidence_score` (0–100, extraction/source
reliability) is deliberately separate from `match_score` (fit to the candidate's profile):
`Match Score: 91, Confidence: 72` means "excellent fit, but the extraction isn't perfectly
reliable" — never conflated into one number.

**Stale detection** (`scripts/lib/staleness.py`): `lifecycle_status` ∈ `NEW / ACTIVE / STALE /
CLOSED / UNCERTAIN`, driven by posting age (configurable thresholds) and explicit closure
evidence in the text. `CLOSED` is never inferred from age alone — only from an actual "position
filled"/"no longer accepting" style marker; a record with no date at all is `UNCERTAIN`, not
guessed as fresh.

**Duplicate intelligence** (`scripts/lib/dedup.merge_duplicates`): the same posting found via
LinkedIn, Indeed, and a company careers page merges into one canonical record with an
`alternate_sources` list — source information is preserved, never dropped, on every merge.

**Company entity resolution** (`scripts/lib/entity_resolution.py`): "Al Futtaim" / "Al-Futtaim" /
"Al Futtaim Group" resolve to one canonical name via exact match on a normalized key (lowercased,
punctuation stripped, common corporate suffixes removed) — deliberately not a fuzzy-ratio match,
so two genuinely different companies are never merged on a "looks similar" guess.

### Web Intelligence CLI

```bash
python career_hunter.py web-search --region global          # generates plan + browser queue, reports SEARCH_PROVIDER_UNAVAILABLE honestly
python career_hunter.py web-search --region europe
python career_hunter.py web-search --region gulf
python career_hunter.py web-search --remote
python career_hunter.py web-search --freelance
python career_hunter.py web-search --region global --dry-run   # plan + coverage only, touches nothing

python career_hunter.py browser-queue --region global          # writes reports/browser_search_queue.md

python career_hunter.py web-import --file data/raw/search_results/linkedin.json
python career_hunter.py web-import --directory data/raw/search_results/
python career_hunter.py web-import --directory data/raw/search_results/ --dry-run

python career_hunter.py research --region gulf                 # Phase 3: runs daily's pipeline + persists a snapshot to data/research_runs/
python career_hunter.py research --region global --dry-run

python career_hunter.py company-sources --add "Acme Architects" --url https://acme.example/careers --source-type architecture_firm --region UAE --priority HIGH
python career_hunter.py company-sources --list
python career_hunter.py company-sources --run                  # checks every enabled company career page
python career_hunter.py company-sources --run --limit 10        # Phase 4: HIGH-priority companies checked first
```

**Phase 4.1 additions (Career Search Modes Engine):** `config/career_state.yaml` records the
user's current primary goal (e.g. `FULL_TIME`) plus any periodic secondary modes (`REMOTE_FULL_TIME`,
`CONTRACT`, `FREELANCE`, `PART_TIME`), each with its own `priority` (HIGH/MEDIUM/LOW),
`frequency` (daily/weekly/monthly), and employment-type query strategy — editable directly, never
hard-coded. `scripts/lib/career_state.py` decides which modes are active and due to run (tracked
in `data/career_mode_runs.json`, not committed); `scripts/career_search_modes.py` runs each due
mode through the existing `scripts.daily_research.run()` pipeline unchanged, splitting a shared
query budget across modes proportional to priority (HIGH:MEDIUM:LOW = 3:2:1) so a low-priority
mode never starves the user's primary goal:

```bash
python career_hunter.py career-state --show                       # current goal + mode due-status
python career_hunter.py career-state --dry-run --limit 60          # plan for every due mode, no writes
python career_hunter.py career-state --mode CONTRACT --region gulf # run one mode regardless of due-ness
python career_hunter.py career-state --all --limit 100             # run every active mode now
```

**Phase 4.2 additions (Opportunity Intelligence & Multi-Mode Resolution):** one job can belong
to several modes but is always **one** canonical record. Each opportunity gets:

| Field | Meaning |
|---|---|
| `matched_modes` | Modes proven by explicit evidence only — the `employment_type`/`remote` fields, or phrases such as "full-time", "6-month contract", "freelance", "fully remote". "Architect needed" matches nothing. |
| `primary_mode` | Highest mode in `ranking.primary_mode_precedence`, or `UNKNOWN`. |
| `mode_match_reasons` | The evidence behind each matched mode. |
| `discovered_via_modes` | Which search mode found it — provenance only, never evidence. |
| `match_score` | The unchanged 100-point fit score. |
| `mode_priority_score` | 0-100 relevance of the job's modes to `current_primary_goal`. |
| `career_priority_score` / `career_priority` | `match_score × (floor + (1−floor) × mode_priority/100)` — mode adjusts priority by at most `1−floor` (25% by default), so it can never make a poor match outrank a strong one. |
| `exceptional_opportunity` / `exceptional_reasons` | Configurable threshold; surfaced and alerted **even outside the current goal**. |

Example: with goal `FULL_TIME`, a full-time job at match 89 ranks above a freelance job at match 96
for the current goal (89 vs 81.6 career priority), while the freelance job is still the best
match — and if it clears `exceptional.min_match_score` it appears under **EXCEPTIONAL
OPPORTUNITIES** with "Outside current primary mode, surfaced because it meets the exceptional
threshold." Exceptional reasons come only from fields the record actually has (match score,
explicitly assessed career-value/compensation sub-scores, direct portfolio project evidence,
explicit remote evidence); reasons such as "prestigious company" or "major project" are never
generated because nothing in the data model supports them.

Rediscovering a job — under another mode, or at another URL — updates its single `jobs.csv` row:
modes and source URLs are unioned, existing evidence is never blanked, and priority is recomputed.
All of it is configured in `config/career_state.yaml` (`ranking`, `exceptional`, `alerts`).

```bash
python career_hunter.py research --mode full_time --dry-run          # one mode, if due (case-insensitive)
python career_hunter.py research --all-modes --dry-run --limit 60    # every enabled mode that is due
python career_hunter.py research --mode freelance --force --dry-run  # --force bypasses the due check only
```

**Phase 4 additions (real job acquisition):** `tracking/source_health.csv` now classifies every
failure into a canonical `error_type` (`TIMEOUT`/`HTTP_403`/`HTTP_401`/`RATE_LIMITED`/
`AUTH_REQUIRED`/`NETWORK_ERROR`/`PARSER_ERROR`/`INVALID_RESPONSE`/`PROVIDER_ERROR`/
`BROWSER_REQUIRED`/`NO_RESULTS`/`SEARCH_PROVIDER_UNAVAILABLE` — see
`scripts/lib/error_types.py`), with the raw error text preserved separately in `error_detail`.
`scripts.lib.source_health.source_priority()` turns that history into a routing priority
(HIGH/MEDIUM/LOW/DISABLED) — a source only drops to LOW after 5+ *consecutive* failures, never
after one. Company career pages now carry a human-supplied `priority` (HIGH/MEDIUM/LOW) so
`company-sources --run --limit N` checks the most relevant companies first. Every normalized
opportunity in a research cycle now carries a `portfolio_evidence_summary` (direct project /
profile capability / regional matches, from `scripts.intelligence.application_strategy
.combined_portfolio_evidence()`), not only the ones that clear the AI-tier threshold — this is
rule-based and costs no AI calls. See `docs/PRODUCTION_READINESS.md` "PHASE 5 — Real Job
Acquisition" for the full provider-by-provider status.

`web-search` never pretends to have searched: with no live search API or browser-automation
session configured (the case in this environment, and by design for BROWSER_REQUIRED sources),
it generates the query plan, writes `reports/browser_search_queue.md`, and reports
`provider_status: SEARCH_PROVIDER_UNAVAILABLE` in its output. `browser-queue` lists each manual
search a human should run (source, query, region, priority, expected value, and exactly what to
do with the results), prioritized by job-title value (BIM Architect/Coordinator/Revit Architect
highest). `web-import` loads, validates, normalizes, extracts, deduplicates (with source
merging), scores, saves to `tracking/jobs.csv`, and routes `COMPANY_SIGNAL` results into
`tracking/companies.csv` as `HIDDEN_OPPORTUNITY` candidates.

## AI Intelligence Engine (V1.4)

The final layer: turns a pile of scored opportunities into "what should I do today, and why."
Conceptually: `LOAD -> ANALYZE -> SCORE -> DECIDE -> NETWORK -> APPLICATION STRATEGY -> RANK ->
REPORT -> LEARN`. `scripts/career_intelligence.py` is the orchestrator; everything it calls lives
in `scripts/intelligence/`.

**AI provider abstraction** (`scripts/intelligence/ai_provider.py`): a generic `AIProvider.analyze(prompt,
context)` interface so no single AI vendor is hard-coded. The default and only implemented
provider is `RuleBasedAIProvider` — deterministic local heuristics, zero network calls, zero API
key. `config/ai.yaml` lists `openai`/`claude`/`local_llm` as placeholders (`implemented: false`);
selecting one falls back to rule-based behavior (wrapped so the fallback is visible), never
silently pretends to call a real API, and never reads/stores a credential in this repo. **The
test suite and every CLI command run with zero API keys.**

**AI cost control (tiers)**, from `config/ai.yaml`:
| Tier | Score | What runs |
|---|---|---|
| 1 | < 70 | Rule-based `match_score` only (V1.1) — no AI analysis |
| 2 | ≥ 70 | `job_analyzer` runs (fit/quality/risk) |
| 3 | ≥ 85 | Same analysis, now at "deep" depth (used for `--deep`) |
| 4 | ≥ 90 | Full application strategy auto-generated, flagged `high_value_application` |

`analyze`/`intelligence` skip tier-1 records by default; `--deep` forces full analysis on every
record regardless of score (useful for manual review of the whole pipeline, at proportionally
higher compute cost — still zero AI-vendor cost, since the only implemented provider is local).

**Job analysis** (`scripts/intelligence/job_analyzer.py`) computes `fit_score`, `quality_score`,
`risk_score` (with named `risk_factors` — missing skills, seniority/location mismatch, visa/salary
uncertainty, weak company info, stale posting, low source confidence), and `ai_opportunity_score`
— **a separate assessment from the V1.1 `match_score`, which is never overwritten.**

**Decision engine** (`scripts/intelligence/decision_engine.py`) always returns one of
`APPLY_NOW / APPLY / NETWORK_FIRST / RESEARCH_COMPANY / CONSIDER / LOW_PRIORITY / SKIP`, with
`why` (grounded bullets), `risks`, and a concrete `next_action` — e.g.:
```
DECISION: APPLY_NOW
WHY: Strong technical/role fit (95.0%); matches BIM Coordination, Facade Design, Revit, Navisworks.
RISKS: No major risks flagged.
NEXT ACTION: Submit a tailored CV and portfolio immediately; identify and contact the BIM/hiring manager.
```
`compute_action_priority()` combines match score, AI opportunity score, confidence, and career
value into one sortable 0–100 number for the daily action queue — it does not replace
`match_score` or `ai_opportunity_score`, both remain visible individually. Every decision is
appended to `tracking/decisions.csv` (opportunity, decision, reason, scores, timestamp, evidence,
next action) for future learning — decision history is never overwritten.

**Skill gap & learning priority** (`scripts/intelligence/skill_gap.py`): each requirement is
`MATCH` / `PARTIAL_MATCH` / `MISSING` / `UNKNOWN` against `config/profile_skills.yaml` (the single
source of truth — never duplicated or guessed). Missing skills are only called `CRITICAL` /
`HIGH_VALUE` / `OPTIONAL` when their observed frequency across `tracking/jobs.csv` actually
supports it; with too few occurrences, the result is `LOW_VALUE` with a note that market-demand
data is insufficient — never an invented "this skill is in demand."

**Company analysis** (`scripts/intelligence/company_analyzer.py`): a `COMPANY_PRIORITY` grade
(`A+`/`A`/`B`/`C`/`D`) from the existing V1.2 `ai_fit_score`, plus hiring/BIM/growth signals and
likely hiring managers cross-referenced from `tracking/networking.csv`. Every dimension with no
real evidence source (market reputation, international activity, project quality) reports
`UNKNOWN` — never guessed. A company with `HIDDEN_OPPORTUNITY` status gets a
`recommended_networking_action` of `NETWORK_FIRST` even with zero public vacancies.

**Personalized outreach** (`scripts/networking_intelligence.generate_personalized_outreach()`):
short, specific connection/follow-up/email drafts grounded in the contact's real company/role/
`why_relevant` context — never the generic "Dear Sir/Madam" template. Drafts only; a human
reviews and sends every message (see LinkedIn policy below).

**Application strategy & CV change plan** (`scripts/intelligence/application_strategy.py`,
`cv_strategy.py`): wraps the existing V1.2 `application_intelligence.py` rather than duplicating
it, adds a `high_value_application` flag at score ≥ 90, and a `CV_CHANGE_PLAN` — "emphasize X",
"move Y higher", "highlight Z projects" — phrased entirely over the candidate's real, existing
profile and the posting's actual matched skills. Never rewrites the CV automatically; never
invents a project, employer, or qualification. Portfolio recommendations honestly report
`PORTFOLIO_DATA_INSUFFICIENT` today, since `config/profile_skills.yaml` only lists project
*types*, not individually named projects — the moment real per-project metadata exists, the same
function returns ranked project recommendations instead.

**Career strategy & market intelligence** (`scripts/intelligence/career_strategy.py`): best
countries/titles/companies/sources/work-modes and weak spots (low-sample sources, application
bottlenecks), built on the existing `weekly_analysis.py` aggregation. `market_intelligence()`
reports skill/title/country demand **with its sample size and a confidence label
(LOW/MEDIUM/HIGH)** every time — never a bare claim like "Germany is best" from one data point.

**Learning engine** (`scripts/intelligence/learning_engine.py`): response/interview/offer rates
and networking response rate, grouped by country/job title/source/company — every rate ships with
its `sample_size`, and segments under the minimum (3) are flagged `insufficient_sample` rather
than used to draw a conclusion. Snapshots are appended to `tracking/learning.csv` on every
`intelligence` run, building history over time.

**Alerts** (`scripts/career_intelligence.generate_alerts()`): machine-readable conditions —
`NEW_EXCEPTIONAL_OPPORTUNITY`, `HIGH_MATCH_JOB`, `HIGH_VALUE_COMPANY`, `NEW_HIDDEN_OPPORTUNITY`,
`FOLLOW_UP_DUE`, `INTERVIEW`, `OFFER` — written to `tracking/alerts.csv`,
`data/alerts/<timestamp>.json`, and `reports/alerts.md`. Nothing is sent automatically; alerts are
for the human to read.

**CAREER COMMAND REPORT**: running `intelligence` overwrites `reports/daily_report.md` with the
decision-first format (Executive Summary, TOP 10 ACTIONS, APPLY NOW, NETWORK FIRST, HIDDEN
OPPORTUNITIES, FREELANCE, FOLLOW UPS, SKILL INTELLIGENCE, MARKET INTELLIGENCE). Running `daily`
alone still writes the original V1.2 report format — nothing about `daily_research.py` changed.

### AI Intelligence CLI

```bash
python career_hunter.py analyze --score-min 70              # tiered AI job analysis, prints decisions, writes nothing
python career_hunter.py analyze --score-min 85 --deep        # forces full analysis regardless of tier
python career_hunter.py decision                             # decision engine only; records to tracking/decisions.csv
python career_hunter.py strategy                             # career strategy report (best countries/titles/companies/sources)
python career_hunter.py learning                             # response/interview/offer rates by segment, with sample sizes
python career_hunter.py market                               # market intelligence: demand signals with sample size
python career_hunter.py alerts                                # writes reports/alerts.md from current tracking data
python career_hunter.py intelligence --score-min 70           # full pipeline: LOAD->ANALYZE->DECIDE->NETWORK->APPLY->REPORT->LEARN
```

`intelligence` LOADs from the JSON snapshots `daily`/`web-import` already save to
`data/processed/` (the only place the full V1.1 sub-scores persist today — `tracking/jobs.csv`
itself doesn't store them), so run `daily` or `web-import` at least once before `analyze`/
`decision`/`intelligence` have anything to analyze. None of these commands send an email, send a
LinkedIn message, apply to anything, or automate a browser — see LinkedIn policy below.

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
- No live web-search API or browser-automation provider is wired up in V1.3 — `web-search`
  always reports `SEARCH_PROVIDER_UNAVAILABLE` here. Real results enter via `web-import` from
  `data/raw/search_results/*.json`, collected by a human (or a separate browser-capable agent
  session) running the queries in `reports/browser_search_queue.md`.
- `page_extractor.py` cannot reliably extract a company name from free-form visible text (too
  error-prone / too easy to fabricate) — company extraction from a page needs structured markup
  (JSON-LD/microdata), which V1.3 doesn't parse yet. From a bare search snippet, company is only
  filled in when a specific pattern ("X is hiring", "join X") supports it; otherwise the record
  is correctly rejected downstream rather than guessed.
- No real AI provider (OpenAI/Claude/local LLM) is implemented in V1.4 — `config/ai.yaml` lists
  them as placeholders only, and selecting one falls back to the rule-based provider rather than
  pretending to call an API. All V1.4 "AI" reasoning today is explainable, deterministic, local
  logic grounded in actual record fields — genuinely useful, but not a language model.
- Portfolio intelligence (`application_strategy.portfolio_recommendation()`) always reports
  `PORTFOLIO_DATA_INSUFFICIENT` because `config/profile_skills.yaml` has no per-project metadata
  (only project *types*) — adding real named projects there would make this functional immediately.
- `career_strategy.market_intelligence()`'s salary pattern is always `DATA_INSUFFICIENT` because
  `tracking/jobs.csv` doesn't persist `salary_min`/`salary_max` columns today (the opportunity
  schema has the fields; the CSV tracker doesn't carry them through) — a real limitation worth
  fixing before salary-pattern analysis can be trusted.
- `scripts.career_intelligence.analyze_opportunities()` reads from `data/processed/*.json`
  snapshots, not `tracking/jobs.csv` directly, because the CSV tracker doesn't persist the full
  V1.1 sub-scores — run `daily`/`web-import` before `analyze`/`decision`/`intelligence`.

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

V1.3 adds coverage for the Web Intelligence Layer: the search-provider interface and
`SEARCH_PROVIDER_UNAVAILABLE` reporting, manual search import (valid/malformed/empty), source
routing (known domains, unknown domains never assumed known, careers-page heuristic), HTML
extraction (titles/headings/skills, JS-required detection, empty/malformed HTML), opportunity
extraction and all four classifications (including that company is never fabricated without
textual support), the browser queue (includes BROWSER_REQUIRED sources even when `enabled:
false`, priority sorting), provenance/confidence population, stale-opportunity detection
(including that CLOSED is never inferred from age alone), source-preserving duplicate merging,
and company entity resolution (merges confident variants, never merges different companies).

V1.4 adds coverage for the AI Intelligence Engine: the provider interface and rule-based fallback
(including an unimplemented-provider configuration falling back safely, with no API key read or
required), job analysis (fit/quality/risk kept separate from match_score, named risk factors),
skill-gap classification (never fabricates a candidate skill), frequency-gated learning priority,
the decision engine (every decision is one of the seven allowed values, always has a reason,
NETWORK_FIRST for hidden opportunities), action priority bounds, company analysis (UNKNOWN for
every unevidenced dimension), CV change plans (never claims an unmatched skill), application
strategy (high-value flag at score ≥ 90), portfolio intelligence (honestly insufficient without
real project metadata), the learning engine (sample-size gating, never computing a rate without a
denominator), market intelligence (sample size + confidence label), alerts (fire on real
conditions only, never on empty input), decision history recording, AI-tier cost control (tier-1
records skipped by default, included with `--deep`), and missing-profile-data handling.
170/170 tests passing as of V1.4.
