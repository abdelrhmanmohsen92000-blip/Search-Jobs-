# Architecture (V1.7)

Career Hunter is a local-first Python application (standard library + `pyyaml` + `jsonschema`;
`pytest` for tests). CSV trackers are the canonical store, JSON holds detail and history,
YAML holds every setting. There is no database server, no background service you must run, and
no web framework.

## Data flow

```
              ┌──────────── acquisition (network; skipped when NETWORK_MODE=offline) ────────────┐
config/*.yaml │ company career pages (JSON-LD JobPosting) · Remote OK · Remotive · Brave Search    │
              │ discovery (needs BRAVE_SEARCH_API_KEY) · manual import (data/raw/*.json) ·         │
              │ web-import (data/raw/search_results/*.json)                                       │
              └───────────────────────────────────────┬───────────────────────────────────────────┘
                                                      ▼
   normalize → validate → mode classification → deduplicate (source/mode-preserving merge)
                                                      ▼
   ANALYSIS (scripts/intelligence/analysis_engine.py)
     requirements extraction (provenance-tagged) → skills gap → 12 dimensions →
     Overall Match / Opportunity / Confidence → decision + reasons + risks + recommendation
     (+ optional LLM pass that may only add items found verbatim in the posting)
                                                      ▼
   tracking/jobs.csv (upsert by id) · tracking/analyses.csv (history) · data/analyses/<id>.json
                                                      ▼
   post_research: networking suggestions → tracking/networking_actions.csv
                  NEW_HIGH_PRIORITY_JOB notifications → tracking/notifications.csv (+ outbox / webhook)
                                                      ▼
   human actions (CLI / dashboard): pipeline moves, networking status, feedback
                                                      ▼
   reports (daily brief, weekly market/skills) · dashboard · learning loop (suggestions only)
```

The scheduler (`scripts/scheduler.py`) runs the same entry points on a cron-like schedule.

## Modules

| Path | Responsibility |
|---|---|
| `career_hunter.py` | CLI. V1.1–V1.4 commands unchanged; V1.4–V1.7 commands in `scripts/cli_commands.py`. |
| `scripts/lib/paths.py` | Repository paths + the **workspace** (tracking/, data/, reports/) — switchable with `--workspace` / `CAREER_HUNTER_WORKSPACE`. |
| `scripts/lib/runtime.py` | `NETWORK_MODE` and the list of environment variables (status only, never values). |
| `scripts/sources/*`, `scripts/web/*` | Acquisition adapters, source health, search discovery, JSON-LD parsing (Phase 3–5, unchanged). |
| `scripts/daily_research.py`, `scripts/research.py` | Research cycle and persisted run snapshots (`data/research_runs/`). |
| `scripts/intelligence/requirements_extractor.py` | Posting → requirements with `field_sources`; skills gap against `config/profile_skills.yaml`. |
| `scripts/intelligence/analysis_engine.py` | 12 dimensions, scores, decision, persistence. |
| `scripts/intelligence/scoring_model.py` | Versioned weights/thresholds (`config/scoring_model.yaml`). |
| `scripts/intelligence/llm_enrichment.py`, `ai_provider.py`, `claude_provider.py` | Optional LLM pass with verification. |
| `scripts/intelligence/company_intel.py` | Company index, score, grade, overrides. |
| `scripts/intelligence/networking_engine.py` | Contact-type suggestions, reasons, angles, drafts; manual status updates. |
| `scripts/intelligence/application_pipeline.py` | Statuses, transitions + event log, board, funnel, packets. |
| `scripts/intelligence/notifications.py` | Event producers + channels (terminal, email outbox, webhook). |
| `scripts/intelligence/insights.py`, `briefs.py` | Job views/filters, skills & market intelligence, daily/weekly reports. |
| `scripts/intelligence/feedback.py`, `learning_loop.py` | Outcome feedback, evaluation, suggestions, approval. |
| `scripts/scheduler.py` | Cron parsing, due logic, tasks, daemon, crontab text. |
| `scripts/dashboard/` | `api.py` (pure JSON handler), `server.py` (stdlib HTTP), `static/` (UI). |
| `scripts/demo.py` | Seeds a SYNTHETIC demo workspace through the real pipeline. |
| Earlier V1.x modules | `career_intelligence.py`, `decision_engine.py`, `job_analyzer.py`, … kept for backward compatibility (legacy `analyze`/`decision`/`intelligence` commands). |

## Data model

Every entity has a stable ID. All files below live in the active workspace.

| Entity | Stable ID | Storage |
|---|---|---|
| Job | `id` — deterministic 16-hex hash of normalized company + title + location + canonical source URL | `tracking/jobs.csv` (one row per job, merged on rediscovery) |
| Analysis | `analysis_id` = `job_id:analyzed_at` | `tracking/analyses.csv` (history), `data/analyses/<job_id>.json` (latest, full) |
| Company | `company_id` = slug of the name | computed index (`company_intel`), facts from `tracking/companies.csv`, `config/target_companies.yaml`, overrides in `config/company_overrides.yaml`, snapshot `data/company_index.json` |
| Application | = job id (`opportunity_id`) | `tracking/applications.csv` |
| Application event | `event_id` = `job_id:at:to_status` | `tracking/application_events.csv` (append-only) |
| Contact | person + company | `tracking/networking.csv`, `tracking/contacts.csv` (you maintain these) |
| NetworkingAction | `action_id` = `job_id:contact-type` | `tracking/networking_actions.csv` |
| Skill | canonical skill name | `config/skills_taxonomy.yaml` (aliases, categories, transferable_from) |
| ResearchRun | `run_id` | `data/research_runs/<run_id>.json` |
| Source | source name | `config/sources.yaml`, health in `tracking/source_health.csv` |
| Feedback | `feedback_id` | `tracking/feedback.csv` (with the recommendation at the time) |
| Notification | `notification_id` = hash(event type, dedup key) | `tracking/notifications.csv`, `data/outbox/email/*.eml` |
| Schedule | job name in `config/schedules.yaml` | state `data/schedule_state.json`, log `data/schedule_log.jsonl` |
| Model version | version string | `config/scoring_model.yaml` (workspace-local copy in isolated workspaces) |
| Learning suggestion | `suggestion_id` | `data/learning/suggestions/<id>.json` |

New CSV columns are always **appended**, so older rows and older readers keep working. Every
CSV write backs up the previous file to `data/archive/`.

## Provenance and UNKNOWN

Each extracted requirement carries a tag in `requirements.field_sources`:

| Tag | Meaning |
|---|---|
| `SOURCE_STRUCTURED` | From structured data (JSON-LD / API fields) |
| `TEXT_EXTRACTED` | Found in the posting text by a deterministic rule |
| `DERIVED` | Computed from other facts (e.g. seniority from years) — labelled, never presented as stated |
| `AI_DERIVED` | Added by the optional LLM pass **and** verified to appear in the posting |
| `UNKNOWN` | Not stated — stays `UNKNOWN` |

Salary, dates, application URLs, job status and company facts are never produced by text
heuristics or an LLM: they come from structured source fields or stay `UNKNOWN`.

## Workspaces

`paths.use_workspace(dir)` re-points every mutable path. The repository itself is the default
workspace (your real data). `career_hunter.py demo` creates `demo_workspace/` (git-ignored) with
header-only trackers and its own copy of the scoring model, so synthetic data and demo learning
approvals can never reach your real trackers or model. The test suite uses the same mechanism
(`tests/conftest.py`).
