# Production Readiness — AI Career Hunter

**Audit date:** 2026-10-06, against commit `0a4aa00` (V1.4) plus the fixes below.
**Scope:** a full inspection of the actual implementation (not prior reports), the end-to-end data
flow, AI provider readiness, web-search readiness, portfolio/salary intelligence, application
tracking, and security — followed by the smallest safe fixes the audit justified. No new
architecture version, no rewrites of working modules.

---

## 1. Current Architecture

```
career_hunter.py (CLI)
  ├─ search / daily / weekly / report              (V1.1/V1.2 — query generation, live source adapters)
  ├─ web-search / browser-queue / web-import        (V1.3 — Web Intelligence Layer)
  └─ analyze / decision / strategy / learning /
     market / alerts / intelligence                 (V1.4 — AI Intelligence Engine)

scripts/
  lib/            shared primitives: paths, config loaders, scoring, normalize, dedup,
                  storage, staleness, entity_resolution
  sources/        live adapters (Remote OK, Remotive — real HTTP), manual_import,
                  generic_search/company_careers (raw-HTML-only stubs)
  web/            search-result → opportunity pipeline: source_router, page_extractor,
                  opportunity_extractor, manual_search_import, search_engine, browser_queue
  intelligence/   ai_provider (+ claude_provider), job_analyzer, skill_gap, decision_engine,
                  company_analyzer, cv_strategy, application_strategy, career_strategy,
                  learning_engine
  daily_research.py / web_research.py / career_intelligence.py   orchestrators

config/           search_matrix.yaml, sources.yaml, profile_skills.yaml, ai.yaml,
                  portfolio_projects.example.yaml (new — schema/example only)
schemas/          opportunity.schema.json, portfolio_project.schema.json (new)
tracking/*.csv    jobs, companies, contacts, networking, applications, decisions,
                  skill_gaps, learning, alerts
data/             raw/ (incl. search_results/), processed/, archive/, alerts/
reports/          daily_report.md, weekly_report.md, weekly_strategy.md,
                  networking_queue.md, browser_search_queue.md, alerts.md
```

---

## 2. Data Flow Audit

```
WEB SOURCE → SEARCH RESULT → EXTRACTION → NORMALIZATION → OPPORTUNITY → DEDUPLICATION →
SCORING → AI ANALYSIS → DECISION → APPLICATION STRATEGY → TRACKING → FOLLOW-UP → OUTCOME → LEARNING
```

| Stage | Where it's stored | Module |
|---|---|---|
| Collection | `data/raw/*.json`, `data/raw/search_results/*.json` | `scripts/sources/*`, `scripts/web/manual_search_import.py` |
| Extraction/Normalization | in-memory → `schemas/opportunity.schema.json` shape | `scripts/lib/normalize.py`, `scripts/web/opportunity_extractor.py` |
| Deduplication | in-memory (`alternate_sources` on the surviving record) | `scripts/lib/dedup.py` |
| Scoring (V1.1) | `tracking/jobs.csv` (now complete — see finding below) + `data/processed/*.json` | `scripts/lib/scoring.py` |
| AI analysis / decision (V1.4) | `tracking/decisions.csv`; not persisted on the opportunity itself | `scripts/intelligence/job_analyzer.py`, `decision_engine.py` |
| Application strategy | generated on demand (score ≥ 80), not persisted separately | `scripts/application_intelligence.py`, `scripts/intelligence/application_strategy.py` |
| Tracking | `tracking/applications.csv` | manual entry today (see §9) |
| Alerts | `tracking/alerts.csv`, `data/alerts/*.json`, `reports/alerts.md` | `scripts/career_intelligence.py` |
| Learning | `tracking/learning.csv` (append-only snapshots) | `scripts/intelligence/learning_engine.py` |

### Finding: the canonical-data-model gap (FIXED in this audit)

**Before:** `tracking/jobs.csv`'s header declared 8 V1.1 sub-score columns
(`technical`/`experience`/.../`compensation`), but neither writer
(`daily_research.py`, `web_research.py`) ever populated them — every row had those columns
blank. That silently forced `scripts/career_intelligence.py` to read the ephemeral
`data/processed/*.json` snapshots instead of the durable CSV tracker, which defeats the point of
having a tracker at all: delete the snapshot and the sub-scores are gone, even though the row is
still sitting in `tracking/jobs.csv`.

**Fix applied (smallest safe change, no architecture rewrite):**
- `scripts/daily_research.py` now exposes one shared `opportunity_to_jobs_row()` that both
  writers call, and it populates all 8 sub-score columns (plus the salary columns — see §6).
- `tracking/jobs.csv`'s header gained those columns (it was already present for the sub-scores;
  salary columns are new). The file was header-only (no data rows), so this is lossless.
- `scripts/career_intelligence.py` gained `load_opportunities_from_jobs_csv()` /
  `opportunity_from_jobs_row()`, which reconstructs a full `scoring_result` straight from a CSV
  row. `load_latest_scored_opportunities()` now treats the CSV as canonical and the JSON
  snapshots as a fallback only for an id not yet in the CSV (so nothing written by an older run
  stops working).
- Verified end-to-end: ran `daily`, deleted every file under `data/processed/`, and re-ran
  `intelligence` successfully from the CSV alone (see `tests/test_production_audit.py`,
  `test_load_latest_scored_opportunities_works_from_csv_alone` and the CSV-priority-on-collision
  test).

**Was this necessary, or was reading from JSON snapshots acceptable?** Not acceptable for a
system meant for daily use: snapshots are timestamped, unbounded, and have no retention
policy (`data/archive/` only backs up CSVs, not snapshots) — losing them (disk cleanup, a
fresh clone, moving machines) would have silently erased the ability to re-analyze anything
already in the "permanent" tracker. The CSV is the one file this system treats as durable
(`scripts/lib/storage.py` backs it up before every write); it needed to actually carry the data
it claims to.

### Other data-flow inconsistencies found (documented, not all fixed — see status table)

- `tracking/jobs.csv`'s `status` column (pipeline state: new/scored/...) and
  `tracking/applications.csv`'s `status` column (application lifecycle: NEW/APPLIED/.../CLOSED)
  are two different enums that happen to share a column name across files. They are not meant to
  be the same value and nothing currently confuses them, but a future contributor reading both
  files side by side could reasonably assume otherwise — worth a one-line clarifying comment in
  each CSV's documentation (not fixed here, to avoid touching more files than the audit justifies).
- `scripts/intelligence/decision_engine.py` writes decision history to `tracking/decisions.csv`
  but nothing currently reads that history back into a later decision (e.g. "I already decided
  SKIP on this exact opportunity yesterday — don't re-surface it as new"). The table exists and
  is correct; the learning loop that would use it does not yet exist. Documented as a next step.
- `tracking/applications.csv` has no `response_date` or any other way to compute response-time
  latency. `scripts/intelligence/learning_engine.py` can compute response/interview/offer *rate*
  but not *time-to-response* — see §9.

---

## 3. AI Provider Readiness — Real Claude Integration

### What was audited
`scripts/intelligence/ai_provider.py` already had a clean `AIProvider` interface
(`analyze(prompt, context)`), a `RuleBasedAIProvider` default, and an `UnimplementedAIProvider`
fallback wrapper — but no provider actually implemented a real HTTP call to any LLM.

### What was built
`scripts/intelligence/claude_provider.py` — a real `ClaudeAIProvider(AIProvider)`:

| Requirement | Implementation |
|---|---|
| Claude as primary reasoning engine | `ClaudeAIProvider` calls `https://api.anthropic.com/v1/messages` |
| Rule-based fallback | Falls back to `RuleBasedAIProvider` on missing key, network failure, non-200, or malformed JSON — labeled, never silent |
| Configurable model | `model` constructor arg, read from `config/ai.yaml` `providers.claude.model` (default `claude-sonnet-5`) |
| Environment-variable API key | Reads `ANTHROPIC_API_KEY` (configurable env var name) at **call time only** — never read, logged, or stored anywhere else |
| Timeout | `timeout` arg (default 20s) |
| Retries | `max_retries` arg (default 2) with exponential backoff; 401/403 are not retried (a bad key won't become a good one) |
| Structured JSON output | System prompt instructs JSON-only output; response is `json.loads`'d, with `MALFORMED_RESPONSE` fallback if that fails |
| Token/cost tracking | Parses `usage.input_tokens`/`usage.output_tokens` from the response into `self.last_usage` |
| Failure fallback | Every failure path (`MISSING_API_KEY`, `API_CALL_FAILED`, `MALFORMED_RESPONSE`) falls back to the rule-based result, clearly labeled |
| No secrets in repo | No key is read from, written to, or referenced by any committed file; `config/ai.yaml` only names the *environment variable* to read |
| No API key needed for tests | `provider: rule_based` remains the default in `config/ai.yaml`; `get_ai_provider()` only constructs `ClaudeAIProvider` when explicitly configured; its own tests monkeypatch the HTTP call |

### What was explicitly NOT assumed, and what was verified instead of assumed
The task instructions were explicit: **do not assume a Claude consumer (claude.ai) subscription
provides API access** — it does not. The Anthropic API is a separate product with its own
console (`https://console.anthropic.com/`), its own billing, and its own key.

What this audit could and did verify directly, since it couldn't take the instruction's word for
it either:
- **This sandboxed environment can reach `api.anthropic.com`** (confirmed with a direct
  `curl -X POST https://api.anthropic.com/v1/messages` → real `401 Unauthorized`, and with
  `ClaudeAIProvider.analyze()` using a fake key → the same real `401` surfaced through the
  adapter's own error handling). Checking `env | grep -i proxy` shows why: this session's own
  proxy configuration lists `api.anthropic.com` in `NO_PROXY` (it talks to Anthropic directly, as
  the platform this session itself runs on) rather than through the general egress proxy —
  so reachability here reflects this session's own infrastructure, not a general "outbound HTTPS
  is allowed" policy. **Do not assume the same holds in a different deployment** (a different
  sandbox, a production server, a CI runner); verify reachability there independently before
  relying on it. This is different from `remoteok.com`/`remotive.com`, which this same
  environment's general-purpose proxy returns `403 connect_rejected` for (an organization-level
  network policy block, not an API-level auth failure) — see README "Sources".
- **What was NOT and could not be verified here:** a successful, authenticated call with a real
  key. This environment has no real `ANTHROPIC_API_KEY` to test with, and none should be placed
  here to find out — that is exactly the "do not assume" instruction. The adapter's request shape
  (headers, body, endpoint, JSON parsing) is written to the publicly documented Messages API
  contract, but **has not been exercised end-to-end against a real, authenticated call**. Verify
  it for real, in an environment with a real key, before depending on it in production.

### To actually turn this on
1. Generate a real API key at `https://console.anthropic.com/` (requires its own billing setup —
   separate from any claude.ai subscription).
2. Export it as an environment variable in whatever runs this code —
   `export ANTHROPIC_API_KEY=sk-ant-...` — never commit it, never put it in `config/ai.yaml`.
3. Set `provider: claude` in `config/ai.yaml` (or construct `ClaudeAIProvider` directly).
4. Run one real call and confirm `status: "OK"` with a sane `result`/`usage` before trusting it
   in a daily cycle; watch for `API_CALL_FAILED`/`MALFORMED_RESPONSE` in early runs.
5. Nothing in `scripts/intelligence/job_analyzer.py`, `decision_engine.py`, etc. currently calls
   `AIProvider.analyze()` — they are the "rule-based tier" by design (see V1.4 cost-control tiers)
   and would need explicit wiring to route specific sub-decisions through an LLM. That wiring is
   a deliberate choice for later, not an oversight: every current “AI” output is
   deterministic and explainable, which is itself a product property worth keeping for some of
   these decisions even after a real LLM is available.

---

## 4. Real Web Search Readiness

### Provider boundary (already correctly designed in V1.3, audited and confirmed sound)
```
WebSearchProvider.search(query, limit) → SearchProviderResult
    │
    ├─ ManualSearchImportProvider   LIVE — reads data/raw/search_results/*.json
    ├─ (future) a real search-API provider — same interface, drop-in
    └─ (future) a browser-session provider — same interface, drop-in
```
`scripts/web/search_engine.run_web_search()` takes a provider or `None`; with `None` it reports
`SEARCH_PROVIDER_UNAVAILABLE` rather than fabricating results — confirmed correct, unchanged.

### Source classification (confirmed accurate against `config/sources.yaml`)
| Class | Examples | What happens today |
|---|---|---|
| API-accessible | Remote OK, Remotive | Real HTTP calls (`scripts/sources/remoteok.py`/`remotive.py`); blocked by *this* environment's network policy (`403` at the proxy), not by the code |
| PUBLIC_WEB (no API) | Indeed, Bayt, GulfTalent, ArchDaily, ... | `generic_search.py`/`company_careers.py` fetch raw HTML only — no parser wired up (deliberate boundary, not a bug) |
| BROWSER_REQUIRED | LinkedIn, Glassdoor, Upwork | Never automated; surfaced in `reports/browser_search_queue.md` for a human to run manually |
| MANUAL | — | `data/raw/search_results/*.json`, fed by a human or a separate browser-capable session |

### To turn `SEARCH_PROVIDER_UNAVAILABLE` into a live workflow
Three independent paths, matching the provider boundary above — none require touching
`scripts/intelligence/` or the scoring/dedup pipeline:
1. **A real search API** (e.g. a commercial job-search or web-search API): implement
   `WebSearchProvider.search()` against it in a new `scripts/web/<name>_provider.py`, following
   `scripts/sources/base.py`'s timeout+retry pattern; register it as the `search_engine.py`
   default provider.
2. **A browser-capable session**: have that session run the queries already listed in
   `reports/browser_search_queue.md`, export results in the `SearchResult` shape documented in
   README "Manual search import", and drop them in `data/raw/search_results/`.
3. **HTML parsers for PUBLIC_WEB boards**: `generic_search.py` already fetches the raw HTML; the
   missing piece per board is a small, board-specific parser extracting job fields from that
   board's result markup (README "How to add a new source" has the exact steps).

No fake results were added anywhere in this audit, and none should be — this remains the
system's one absolute rule.

---

## 5. Portfolio Intelligence

**Audited finding:** `config/profile_skills.yaml` lists project *type categories*
(Residential, Luxury Villas, ...) but no individually named projects — so
`scripts/intelligence/application_strategy.py:portfolio_recommendation()` has always had nothing
to recommend from, and correctly reports `PORTFOLIO_DATA_INSUFFICIENT` rather than inventing one.
**No portfolio data exists anywhere in this repository to extract.**

**What was added (schema + example only, per the task's explicit instruction not to fabricate):**
- `schemas/portfolio_project.schema.json` — the smallest useful per-project structure: name,
  project_types, location, area, role, responsibilities, software, BIM level, disciplines,
  deliverables, architectural/interior/exterior/landscape/visualization scope flags, status, and
  measurable achievements. `name`/`project_types` are the only required fields.
- `config/portfolio_projects.example.yaml` — a clearly labeled EXAMPLE file (every value says
  "EXAMPLE —"), showing exactly where to add real entries
  (`config/profile_skills.yaml`'s `portfolio_projects:` key) and validated against its own schema
  in `tests/test_production_audit.py`.
- Verified the mechanism itself works correctly the moment real data exists:
  `portfolio_recommendation()` returns a real ranked match when a `portfolio_projects` list with
  matching `project_types` is present — confirmed with a test fixture, never left as an assumption.

**Next step for the candidate:** fill in real projects following the example's structure. Nothing
else needs to change in the codebase for this to start working.

---

## 6. Salary / Market Intelligence

**Audited finding:** `schemas/opportunity.schema.json` already had `salary_min`/`salary_max`/
`salary_currency`, but (a) the schema had no way to distinguish a disclosed figure from an
estimate, and (b) **`tracking/jobs.csv` never persisted any salary field at all** — so
`scripts/intelligence/career_strategy.market_intelligence()`'s salary section was always
`DATA_INSUFFICIENT`, correctly, but for the wrong reason (missing plumbing, not missing demand).

**Fix applied (smallest safe schema/tracker extension):**
- `schemas/opportunity.schema.json` gains `salary_period` (year/month/day/hour/project),
  `salary_source` (free text, e.g. "posting" vs. "estimate"), and `salary_confidence`
  (`OBSERVED` / `ESTIMATED` / `LOW_CONFIDENCE`) — all optional, backward-compatible, never
  defaulting to `OBSERVED`.
- `tracking/jobs.csv` gained all 6 salary columns (`salary_min`, `salary_max`,
  `salary_currency`, `salary_period`, `salary_source`, `salary_confidence`), populated by the
  same `opportunity_to_jobs_row()` fix from §2.
- `market_intelligence()` now separately counts `salary_observed_count` vs.
  `salary_estimated_count`, and only ever calls something a "pattern" when the **observed** count
  meets the minimum sample size — an estimate-heavy sample is reported as exactly that, never
  upgraded to a disclosed-salary claim.
- Verified end-to-end with a real salary-bearing test fixture (cleaned afterward) — the full
  chain (extraction → CSV → market intelligence) now carries the figure correctly.

**Still true:** zero real salary data exists in the repository today, by design — this fix makes
the plumbing correct; it does not and should not conjure numbers.

---

## 7. Application Tracking — Lifecycle Audit

Status enum (`tracking/applications.csv`): `NEW → REVIEW → READY_TO_APPLY → APPLIED → FOLLOW_UP →
INTERVIEW → OFFER → ACCEPTED/REJECTED → CLOSED`. All transitions are representable; nothing in
the codebase enforces illegal transitions (e.g. `NEW → OFFER` directly), which is acceptable for
a human-maintained CSV but worth knowing.

| Question | Answerable today? | How / gap |
|---|---|---|
| How many applications sent? | **Yes** | `len(applications)` filtered to `APPLIED`+ statuses (`learning_engine.py`) |
| Best countries/titles/companies by response? | **Yes** | `learning_engine.response_rate_by("country"/"job_title"/"company")`, sample-size gated |
| Best sources for interviews? | **Yes** | `learning_engine.interview_rate_by("source")` |
| Best CV version? | **Partial** | `cv_version` column exists; nothing yet correlates it to outcome — would need a `learning_engine.rate_by("cv_version", ...)` call, trivial to add once ≥3 applications share a CV version |
| Networking actions that produce results? | **Partial** | `networking_response_rate()` gives an aggregate rate; nothing yet links a specific `tracking/networking.csv` row to a specific application outcome |
| Average time to response? | **No** | `applications.csv` has no `response_date`/timestamp distinct from `application_date` and `status`; would need one new column |
| Interview/offer conversion rate? | **Yes** | `learning_engine.interview_rate_by/offer_rate_by`, sample-size gated |
| Rejection patterns? | **Partial** | Rejection *rate* by segment is computable; a "why" (e.g. correlated missing skill) is not — would need `decisions.csv` ↔ `applications.csv` joined by `opportunity_id`, which the schema supports but no code does yet |
| Skill gaps correlated with rejection? | **No** | Same join as above, not implemented |

None of these gaps were fixed in this audit — they require either a new column
(`response_date`) or a join/correlation feature that goes beyond "smallest safe fix." They are
listed here as the concrete next steps (see §13 and the final report).

---

## 8. Security Considerations

- **No API keys anywhere in this repository**, confirmed by grep (`sk-ant`, `sk-`, common key
  patterns) and by design: `config/ai.yaml` only names *environment variable* names to read, never
  values. `scripts/intelligence/claude_provider.py` reads `os.environ` at call time only.
- `.gitignore` already excludes `__pycache__`/`.pytest_cache`; no `.env` file exists or is
  referenced — nothing to accidentally commit.
- Live source adapters (`scripts/sources/remoteok.py`, `remotive.py`) and the Claude adapter both
  use `urllib` directly against fixed, hardcoded HTTPS endpoints — no user-controlled URL is ever
  interpolated into a request without going through `scripts/web/source_router.py`'s
  allow-list-style domain matching first.
- `scripts/web/page_extractor.py` parses HTML with `html.parser` (stdlib, no external XML/HTML
  library with known XXE-class vulnerabilities) and never executes or evaluates fetched content.
- No code path in this repository sends email, posts to LinkedIn, or performs any browser
  automation — confirmed by `grep -r` for `smtplib`, `selenium`, `playwright`, `requests.post`
  used against a social platform: none found outside this audit's own search.

---

## 9. LinkedIn / Human-in-the-Loop Policy (unchanged, re-confirmed)

```
RESEARCH → PREPARE → HUMAN APPROVAL → ACTION → TRACK
```
Re-confirmed by inspection: `scripts/networking_intelligence.py` and
`scripts/intelligence/*` only ever **draft** (`generate_personalized_outreach`,
`reports/networking_queue.md`) — no function anywhere sends a request, message, like, or comment,
scrapes protected data, or performs bulk actions. This audit added no exceptions.

---

## 10. Component Status Table

| Component | Status | Blocker | Next Step |
|---|---|---|---|
| Opportunity schema | READY | — | — |
| Scoring engine (V1.1) | READY | — | — |
| `tracking/jobs.csv` as canonical store | READY (fixed this audit) | — | — |
| Deduplication (exact+fuzzy, source-preserving) | READY | — | — |
| Company entity resolution | READY | — | — |
| Stale detection | READY | Conservative by design (age-only ⇒ STALE, never CLOSED) | — |
| Source adapters: Remote OK, Remotive | PARTIAL | Live in code; blocked by *this* environment's egress policy | Run in an environment that allows the hosts |
| PUBLIC_WEB board parsing | PLACEHOLDER | No per-board HTML parser implemented | Implement one parser per board (see README) |
| BROWSER_REQUIRED sources | MANUAL (by design) | Platform ToS | Human runs `browser_search_queue.md` |
| Web search provider | BLOCKED | No live search API/browser session configured | Wire a real provider (see §4) |
| AI provider: rule-based | READY | — | — |
| AI provider: Claude adapter | PARTIAL | Implemented; not verified against a real authenticated call (no key available here) | Test with a real `ANTHROPIC_API_KEY` in an environment that has one |
| AI provider: OpenAI/local LLM | PLACEHOLDER | Not implemented | Implement following `claude_provider.py`'s pattern if needed |
| Job analyzer / decision engine | READY | — | — |
| Company analyzer | PARTIAL | Several dimensions (market reputation, international activity) are honestly `UNKNOWN` — no evidence source exists | Add a real evidence source if this matters |
| CV strategy | READY | — | — |
| Application strategy | READY | — | — |
| Portfolio intelligence | PLACEHOLDER | No real project metadata exists | Candidate fills in `config/profile_skills.yaml` `portfolio_projects` per the new schema/example |
| Salary / market intelligence | PARTIAL (fixed this audit) | Plumbing now correct; zero real salary observations logged yet | Log real salary figures as jobs are found |
| Career strategy / learning engine | READY | Needs volume to be useful (sample-size gated by design) | Keep logging applications |
| Alerts | READY | — | — |
| Application tracking: core fields | READY | — | — |
| Application tracking: time-to-response, CV/networking correlation | PARTIAL | Missing `response_date` column; no join logic | Add column + a `learning_engine.rate_by("cv_version", ...)` call |
| LinkedIn human-in-the-loop policy | READY | — | — |
| Security (no secrets, fixed endpoints) | READY | — | — |
| CLI | READY | — | — |
| Tests | READY | 195/195 passing | Keep adding as real data sources come online |

---

## 11. Current Limitations (unchanged from V1.1–V1.4 unless noted)

- This sandboxed environment blocks `remoteok.com`/`remotive.com` at the network-policy level but
  allows `api.anthropic.com` — both facts independently verified in this audit, not assumed.
- No real LLM call has been verified end-to-end (would need a real `ANTHROPIC_API_KEY`, which must
  never be placed in this repository to test).
- No real portfolio or salary data exists in the repository; the plumbing for both is now correct
  and tested, but produces nothing until a human supplies real data.
- `tracking/applications.csv` cannot yet answer time-to-response or CV/networking-correlated
  outcome questions — needs one new column and a small join, not implemented in this audit.
- PUBLIC_WEB job boards have no HTML parser; browser-required boards are correctly never automated.

## 12. Recommended Next Implementation Steps

1. **Verify the Claude adapter against a real API key** in an environment that has outbound
   access and a real `ANTHROPIC_API_KEY` set as an environment variable (never committed) — this
   is the one piece of V1.4's AI layer that is implemented but genuinely unverified.
2. **Add `response_date` to `tracking/applications.csv`** and a `learning_engine.rate_by()`
   helper generalized over any column (country/job_title/source/company/cv_version), so CV-version
   and time-to-response questions become answerable with the same sample-size discipline already
   used elsewhere.
3. **Fill in real portfolio data** in `config/profile_skills.yaml` following
   `schemas/portfolio_project.schema.json` / `config/portfolio_projects.example.yaml` — this
   activates `portfolio_recommendation()` with zero code changes, verified in this audit.

---

## PHASE 2 — Real Claude + Portfolio Intelligence

**Audit date:** 2026-10-06, continuing from the Phase 1 baseline (commit `f550fec`).

### What was implemented

1. **Personal profile audit (§1 of the Phase 2 brief).** Inspected `profile/profile.md` and
   `config/profile_skills.yaml` directly rather than trusting the task brief's own summary of the
   candidate's skills. Finding: the existing files are **already more authoritative** than the
   brief's list — they additionally record real employers (EDEC, Al-ORABI Engineering Consulting,
   VISION INTERNATIONAL GROUP, DIZ Studio, freelance work), education, languages, timezone, and
   relocation preference, none of which the brief's summary included. No fabrication was needed or
   added; the profile structure is already sufficient for the scoring/AI-analysis code that reads
   it (`scripts/lib/scoring.py`, `scripts/intelligence/skill_gap.py`). **No change made** — audited
   and confirmed sufficient, not rewritten.
2. **Portfolio data (§2).** Searched the entire repository for any CV, resume, or portfolio file
   (`find . -iname "*cv*" -o -iname "*resume*" -o -iname "*portfolio*"`, plus a check for any
   `.pdf`/`.docx`) — **none exists**. `profile/profile.md` records employers and broad
   project-*type* categories (Residential, luxury villas, commercial, ...) but no individually
   named project with a location, area, date, or specific deliverables. Per the explicit
   instruction not to fabricate a project name, area, location, client, value, role, LOD,
   deliverables, dates, responsibilities, or status: **no portfolio project entries were
   invented.** Instead, `profile/portfolio-intake.md` was created — one stub section per real,
   verified employer, every field beyond the employer name marked `UNKNOWN`, with instructions for
   where real entries go once supplied (`config/profile_skills.yaml`'s `portfolio_projects:` key,
   validated against `schemas/portfolio_project.schema.json`).
3. **Portfolio → job matching (§3).** `scripts/intelligence/application_strategy.py` gained
   `match_portfolio_projects(opportunity, profile)`, producing exactly the conceptual shape from
   the brief:
   ```
   {"project": "<name>", "evidence": ["project type(s): ...", "software: ...", "disciplines/skills: ..."],
    "relevance": "HIGH"/"MEDIUM"/"LOW", "confidence": "HIGH"/"MEDIUM"/"LOW"}
   ```
   `relevance` is driven only by how many independent evidence dimensions (project type, software,
   discipline/skill) actually overlap between the opportunity and a real project record — never a
   vague similarity score. `confidence` reflects how complete that project's own recorded metadata
   is (a project with almost no filled-in fields can't support a high-confidence match even with
   one lucky overlap). Returns `PORTFOLIO_DATA_INSUFFICIENT` when there is no portfolio data or no
   project has any real evidence — verified with a worked example (synthetic, test-only) producing
   `HIGH`/`MEDIUM`/`LOW` correctly on both axes, and verified that a project with zero genuine
   overlap is never force-matched.
4. **Claude provider audit and hardening (§4).** Reviewed `scripts/intelligence/claude_provider.py`
   against the full checklist:

   | Item | Before this phase | After this phase |
   |---|---|---|
   | Endpoint | `https://api.anthropic.com/v1/messages`, fixed | unchanged |
   | Auth | `x-api-key` header from `ANTHROPIC_API_KEY` env var | unchanged |
   | Model config | constructor arg / `config/ai.yaml` only | **now also overridable via `ANTHROPIC_MODEL` env var** (configurable env var name) |
   | Timeout | 20s default, constructor-configurable | unchanged |
   | Retries | 2 default, skips retry on 401/403 | unchanged |
   | Malformed response handling | `MALFORMED_RESPONSE` status + fallback | unchanged |
   | Structured output | JSON-only system prompt + `json.loads` | unchanged |
   | Fallback behavior | always falls back to `RuleBasedAIProvider`, labeled | unchanged |
   | Env var handling | key read at call time only, never stored | unchanged |
   | Error reporting | single `API_CALL_FAILED` status for all transport failures | **now distinguishes `TIMEOUT` / `HTTP_ERROR` / `API_CALL_FAILED`**, verified against both a mocked and a real `socket.timeout` exception path |
   | Token/cost metadata | `usage.input_tokens`/`output_tokens` parsed | unchanged |
   | Max tokens | hardcoded `1024` | **now configurable** (`max_tokens` constructor arg / `config/ai.yaml`) |

   `config/ai.yaml` was updated to document `model_env_var`, `max_tokens`, and to correct a stale
   claim (see "What was verified" below).
5. **AI output safety gate (§8).** Added `scripts/intelligence/ai_provider.validate_ai_output()`:
   a single, reusable validator any future caller MUST pass an `AIProvider.analyze()` result
   through before writing it into `tracking/decisions.csv`, `tracking/alerts.csv`, or an
   application strategy. Collapses every non-success provider status (missing key, timeout, HTTP
   error, malformed JSON, not-implemented) into one uniform `AI_OUTPUT_INVALID` shape with the
   original status preserved for debugging, and separately validates the parsed result's shape
   (type + required keys) when the call did succeed — never trusts a Claude response blindly, and
   never raises on garbage input. **Not yet wired into any caller**, because no current code path
   routes a Claude response into a decision — `job_analyzer`/`decision_engine` remain deliberately
   rule-based (see Phase 1's AI cost-control tiers). This gate is the integration point for when
   that wiring is added later.
6. **AI cost control (§7).** Unchanged and re-confirmed: `scripts/intelligence/ai_provider.py`'s
   `tier_for_score()` still gates all analysis by `match_score` (tier 1 `<70` rule-based only,
   tier 2 `≥70`, tier 3 `≥85`, tier 4 `≥90` full strategy), and nothing added this phase calls the
   Claude adapter automatically from the pipeline — `ClaudeAIProvider` is only ever invoked
   explicitly (directly, or via `get_ai_provider({"provider": "claude", ...})`), so there is no
   path to unbounded API usage from routine `daily`/`intelligence` runs.

### What was VERIFIED vs. MOCKED vs. UNKNOWN vs. BLOCKED

| Claim | Status | Evidence |
|---|---|---|
| This environment can reach `api.anthropic.com` | **VERIFIED** | Direct `curl -X POST https://api.anthropic.com/v1/messages` → real `401 Unauthorized`; `ClaudeAIProvider.analyze()` with a fake key reproduced the same real `401` through its own error path (not mocked) |
| `ClaudeAIProvider`'s timeout/HTTP-error/malformed-response/fallback logic is internally correct | **VERIFIED (via mocks + one real exception path)** | `tests/test_production_audit.py` monkeypatches `_post_with_retries` for the HTTP/timeout/malformed/success cases (mocked transport, real logic), AND separately monkeypatches `urllib.request.urlopen` to raise a genuine `socket.timeout` to exercise the real classification code, not just the mock |
| A real, authenticated Claude API call succeeds end-to-end | **BLOCKED** | No real `ANTHROPIC_API_KEY` exists in this environment; `scripts/intelligence/smoke_claude.py` reports `REAL_AUTHENTICATED_TEST = BLOCKED, REASON = ANTHROPIC_API_KEY not available` — run directly, not fabricated |
| A claude.ai consumer subscription provides API access | **Confirmed FALSE** (by design/documentation, not something this environment could test) | Anthropic's own account model: console API keys are a separate product/billing from claude.ai — stated plainly in `claude_provider.py` and `config/ai.yaml`, not assumed to be true or false without that basis |
| Portfolio matching logic produces correct HIGH/MEDIUM/LOW relevance and confidence | **VERIFIED** | `tests/test_production_audit.py` worked examples (synthetic, not real candidate data) confirm 2+ dimension overlap → HIGH, 1 → MEDIUM, 0 → `PORTFOLIO_DATA_INSUFFICIENT`, and sparse metadata caps confidence at LOW even with a relevant match |
| Real portfolio data exists for this candidate | **UNKNOWN / not available** | No CV/resume/portfolio file found anywhere in the repository; `profile/portfolio-intake.md` created as the structured next step, with zero fabricated entries |

### Real API smoke test (§5) — exact result from this session

```
$ python3 scripts/intelligence/smoke_claude.py
{
  "REAL_AUTHENTICATED_TEST": "BLOCKED",
  "REASON": "ANTHROPIC_API_KEY not available"
}
```
This is the literal, unedited output. No personal data was or would be sent in this prompt (the
smoke prompt is `Reply with exactly the JSON object {"ok": true} and nothing else.`, with empty
context). The script is intentionally named to avoid pytest's `test_*.py`/`*_test.py` discovery
patterns, so it never runs automatically inside the normal test suite — the 212 tests in `pytest
-q` exercise its logic only via explicit monkeypatched unit tests
(`test_smoke_claude_blocked_without_api_key`, `..._verified_on_simulated_success`,
`..._failed_is_never_reported_as_verified`), never a real network call.

### How to configure the provider (unchanged mechanism, now documented fully)

```yaml
# config/ai.yaml
provider: claude          # default remains rule_based
providers:
  claude:
    api_key_env_var: ANTHROPIC_API_KEY   # NEVER put the key itself here
    model: claude-sonnet-5                # fallback if ANTHROPIC_MODEL env var is unset
    model_env_var: ANTHROPIC_MODEL        # overrides `model` above at call time
    timeout_seconds: 20
    max_retries: 2
    max_tokens: 1024
```
```bash
export ANTHROPIC_API_KEY=sk-ant-...   # shell only, never committed
python3 scripts/intelligence/smoke_claude.py
```

### Security re-check (§11)

Full-repository grep for `ANTHROPIC_API_KEY`, `sk-ant-`, `api_key`, `secret`, `token` run at the
end of this phase: every `ANTHROPIC_API_KEY` match is the *environment variable name* (never a
value); every `sk-ant-` match is an obviously-fake, non-functional test placeholder
(`sk-ant-test-not-real`) used only inside `monkeypatch.setenv(...)` calls that pytest reverts
after each test, or a truncated example in documentation (`sk-ant-...`). No `api_key=`/`secret=`/
`token=` assignment pattern found anywhere. `ANTHROPIC_API_KEY` is confirmed unset in this
session's shell environment throughout.
