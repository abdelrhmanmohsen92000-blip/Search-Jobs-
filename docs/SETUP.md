# Setup — local and cloud (V1.7)

## Requirements

- Python 3.9+ (3.11+ recommended; uses `zoneinfo`)
- `pip install pyyaml jsonschema pytest`
- Nothing else: no database, no Node, no web framework. The dashboard uses the Python standard library.

```bash
git clone <your repo> && cd Search-Jobs-
pip install pyyaml jsonschema pytest
python -m pytest -q                    # all tests run offline
python career_hunter.py config --validate
```

## Try it safely first (synthetic demo)

```bash
python career_hunter.py demo --with-activity        # creates ./demo_workspace (git-ignored)
python career_hunter.py --workspace demo_workspace jobs
python career_hunter.py --workspace demo_workspace dashboard
```

The demo runs the real pipeline on `fixtures/synthetic_jobs.json` with `NETWORK_MODE=offline`.
Every demo company is named `[SYNTHETIC] …`; your real `tracking/` is never touched.

## Local workstation (recommended for live research)

```bash
export NETWORK_MODE=local                       # default
export BRAVE_SEARCH_API_KEY=...                 # optional: enables search discovery
python career_hunter.py research --dry-run
python career_hunter.py research
python career_hunter.py report daily
python career_hunter.py dashboard               # http://127.0.0.1:8765
```

On Windows PowerShell use `$env:NETWORK_MODE="local"` instead of `export`.

## Cloud environments

Career Hunter runs unchanged in a cloud container (`NETWORK_MODE=cloud` just labels the run).
What matters is the environment's **outbound network policy**: it must allow the hosts you want
researched, otherwise those requests fail with `BLOCKED` and are reported in `source-health`
(never hidden, never faked). With a restrictive policy, set `NETWORK_MODE=offline` and use
`web-import` / manual import; analysis, reports, dashboard and learning all keep working.

Hosts to allow for full live research:

| Purpose | Hosts |
|---|---|
| Company career pages | each careers domain in `tracking/company_career_pages.csv` / `config/target_companies.yaml` |
| Remote OK / Remotive | `remoteok.com`, `remotive.com` |
| Search discovery | `api.search.brave.com` (+ the job pages it returns) |
| Optional LLM pass | `api.anthropic.com` |
| Optional webhook | your webhook host |

Known state of this repository's own cloud sandbox: the agent proxy returns HTTP 403 for job and
career hosts, so live acquisition could not be demonstrated there. That is an environment
limitation; the same commands work where egress is allowed.

## Environment variables

Secrets are read from the environment only — never from config files, never printed
(`config` shows only `set` / `not set`).

| Variable | Required | Purpose |
|---|---|---|
| `NETWORK_MODE` | no | `local` (default) · `cloud` · `offline` (no request is ever made) |
| `CAREER_HUNTER_WORKSPACE` | no | Directory for `tracking/`, `data/`, `reports/` (same as `--workspace`) |
| `BRAVE_SEARCH_API_KEY` | no | Brave Search discovery; without it search is `AUTH_REQUIRED` and research continues |
| `ANTHROPIC_API_KEY` | no | Optional LLM enrichment when `config/ai.yaml` has `provider: claude` |
| `ANTHROPIC_MODEL` | no | Override the Claude model in `config/ai.yaml` |
| `CAREER_HUNTER_WEBHOOK_URL` | no | Webhook notifications (only if enabled in `config/notifications.yaml`) |
| `CAREER_HUNTER_TIMEZONE` | no | Override the scheduler timezone (default `Africa/Cairo`) |

## Configuration files

| File | What you set there |
|---|---|
| `config/profile_skills.yaml`, `profile/profile.md` | Who you are: skills, software, years, project types |
| `config/portfolio_projects.yaml` | Your real portfolio projects (evidence for decisions) |
| `config/career_state.yaml` | Current goal (e.g. FULL_TIME) and search modes |
| `config/search_matrix.yaml` | Role families and target regions (Saudi Arabia P1, UAE P2, Qatar P3, Egypt P4, Global/Remote P5) |
| `config/target_companies.yaml`, `tracking/company_career_pages.csv` | Companies to watch and their verified careers URLs |
| `config/skills_taxonomy.yaml` | Skills, aliases, categories, transferable relationships, eligibility-barrier patterns |
| `config/scoring_model.yaml` | Versioned weights and decision thresholds (changed only via approved versions) |
| `config/company_overrides.yaml` | Manual company grades/notes (always win) |
| `config/application.yaml` | CV / portfolio versions (set `file:` to your documents), follow-up timing, Kanban columns |
| `config/networking.yaml` | Contact types per role family, eligibility, follow-up days |
| `config/notifications.yaml` | Channels and event thresholds (e.g. opportunity ≥ 85) |
| `config/schedules.yaml` | Recurring jobs (cron) and timezone |
| `config/learning.yaml` | Learning loop thresholds (default 50 outcomes) |
| `config/ai.yaml` | Optional LLM provider (default `rule_based`) |

## Optional: LLM enrichment

1. Create an API key at https://console.anthropic.com/ and `export ANTHROPIC_API_KEY=...`.
2. In `config/ai.yaml` set `provider: claude` (model `claude-opus-5-5` by default).
3. Only jobs above the AI tier (`tiers.tier_2_min`) are sent, and only items the model copies
   verbatim from the posting are kept (`AI_DERIVED`). Salary, dates, URLs, company facts and job
   status are never taken from the model.
