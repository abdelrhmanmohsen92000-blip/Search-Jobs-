# Operations — daily use, CLI, scheduler, notifications (V1.7)

## A normal day

| When | What happens | Who |
|---|---|---|
| 07:30 Mon/Thu | `company_monitoring` checks configured career pages, refreshes company grades | scheduler |
| 08:00 | `daily_research`: research → analysis → decisions → networking suggestions → notifications | scheduler |
| 08:15 | `daily_report`: Daily Career Brief → `reports/daily_brief.md` | scheduler |
| Morning | Read the brief (or dashboard Overview). Open each 🔥 APPLY_NOW: `job ID`, `application ID` | **you** |
| Morning | Apply on the employer's site yourself, then `application ID --status APPLIED` (or drag the card) | **you** |
| Morning | For 🔵 NETWORK_FIRST: `networking --show ACTION_ID`, send the draft yourself, `networking --done ACTION_ID` | **you** |
| 10:00 / 10:15 | Application + networking follow-up reminders, interview/offer notifications | scheduler |
| Any time | Outcomes: `feedback interview ID`, `feedback rejection ID --reason="…"`, `feedback offer ID` | **you** |
| Sunday 09:00 / 09:15 | Weekly market report, weekly skills-gap report | scheduler |
| Monthly-ish | `learning evaluate` → review suggestion → `learning approve ID --activate` if you agree | **you** |

## CLI reference

Global: `python career_hunter.py [--workspace DIR] <command> …`

| Command | Purpose |
|---|---|
| `research [--dry-run] [--region R] [--mode M | --all-modes] [--force]` | Research cycle; `--dry-run` shows routing and touches nothing |
| `jobs [--country --city --role --company --employment-type --remote true|false --freshness --status --decision --min-score N --search T --sort F --asc --active --limit N --json]` | Filter/sort analyzed jobs |
| `job JOB_ID [--json]` | Decision, reasons, risks, recommendation, 12 dimensions, skills gap, requirements + provenance, networking |
| `companies [--limit N]` / `company ID_OR_NAME` | Company ranking (A+ … D) / one company |
| `applications [--list | --list-pending]` | Pipeline board (or the pre-V1.4 listing) |
| `application JOB_ID [--status S --note T --force] [--interview-date D --follow-up-date D --cv-version V --portfolio-version V --contact-person P] [--write] [--json]` | Packet, moves, edits |
| `networking [--refresh] [--show ID] [--approve|--done|--replied|--no-response|--dismiss ID] [--note T]` | Suggestions and drafts; your manual status updates. `--from-json`, `--generate-queue` still work |
| `skills [--json]` · `market [--json]` | Skills intelligence · market intelligence |
| `report daily` · `report weekly` | Daily Career Brief · weekly market + skills (+ legacy weekly report/strategy). Bare `report` keeps its old meaning (daily cycle + weekly rollup) |
| `feedback KIND JOB_ID [--reason T] [--rating good|bad] [--note T]` | KIND: application, interview, rejection, offer, no_response, withdrawn, job |
| `learning [evaluate | suggestions | approve ID [--activate] | reject ID [--reason T]]` | Learning loop (bare `learning` = segment rates + loop status) |
| `schedule list | run-due [--dry-run] | run JOB | daemon [--interval S] | cron` | Scheduler |
| `notifications [--all] [--mark-read]` | Your notification inbox |
| `dashboard [--host H --port P] [--check]` | Local web dashboard |
| `reanalyze [JOB_ID]` | Re-run analysis of stored jobs with the active model version (e.g. after approving a learning suggestion) |
| `config [--validate] [--model-version V]` | Settings summary, validation, switch active model version |
| `demo [--workspace DIR] [--with-activity] [--reset]` | Synthetic demo workspace |
| `sources` · `source-health` · `research-status [--last N]` | Source registry, health/cooldowns, recent runs |

Older commands (`search`, `score`, `daily`, `weekly`, `web-search`, `browser-queue`, `web-import`,
`analyze`, `decision`, `strategy`, `alerts`, `intelligence`, `career-state`, `company-sources`)
are unchanged.

Job IDs accept a unique prefix (`job 965e7f`).

## Pipeline statuses

`DISCOVERED → VERIFIED → ANALYZED → SHORTLISTED → READY → APPLIED → FOLLOW_UP → INTERVIEW → OFFER`,
or `REJECTED` / `WITHDRAWN` / `CLOSED`. Jobs without an application record show a derived status
(ANALYZED when analyzed, CLOSED when the posting is closed). Every move is appended to
`tracking/application_events.csv` with timestamp and actor (`human:cli`, `human:dashboard`,
`human:feedback`). `APPLIED` and later can only be set by a human. Reopening a closed-out
application needs `--force`. Moving to APPLIED sets `application_date` and a follow-up date
(`config/application.yaml`).

## Scheduler

`config/schedules.yaml` holds the jobs (standard 5-field cron) and the timezone
(`Africa/Cairo` by default, `CAREER_HUNTER_TIMEZONE` overrides). `run-due` runs every job whose
scheduled time passed since its last run (within `catch_up_hours`), so it is safe to call often.
A failing task is recorded (`FAILED` in `schedule list`, details in `data/schedule_log.jsonl`)
and never stops the others.

Pick one driver:

- **Linux/macOS cron** — `python career_hunter.py schedule cron` prints a ready crontab. Option A
  (recommended) is one line running `schedule run-due` every 15 minutes.
- **Windows Task Scheduler** — create a task every 15 minutes running
  `python C:\path\to\career_hunter.py schedule run-due` in the repository folder.
- **Local loop** — `python career_hunter.py schedule daemon` (Ctrl+C to stop).
- **Cloud scheduler / routine** — any scheduler that can run a command: run
  `python career_hunter.py schedule run-due` (or `schedule run daily_research`) periodically
  in an environment with the repository checked out. Persist `tracking/`, `data/`, `reports/`
  between runs (commit them, or point `CAREER_HUNTER_WORKSPACE` at durable storage).

## Notifications

Events: `NEW_HIGH_PRIORITY_JOB` (decision APPLY_NOW, or APPLY/NETWORK_FIRST with opportunity ≥ 85 —
configurable), `APPLICATION_FOLLOWUP`, `NETWORKING_FOLLOWUP`, `INTERVIEW`, `OFFER`,
`SOURCE_FAILURE` (≥ 2 consecutive failures, excluding expected `AUTH_REQUIRED`/offline),
`WEEKLY_REPORT`. Each is recorded once (dedup key) in `tracking/notifications.csv` and delivered to:

- **terminal** — printed by the command that raised it;
- **email (outbox)** — a ready `.eml` file in `data/outbox/email/`; never sent;
- **webhook** — JSON POST to `CAREER_HUNTER_WEBHOOK_URL`, only when enabled in
  `config/notifications.yaml` and not offline (works with Slack/Discord/ntfy/Zapier-style hooks).

Notifications go only to you; nothing contacts a recruiter or company.

## Troubleshooting

| Symptom | Check |
|---|---|
| Research finds nothing | `source-health` (BLOCKED = network policy; AUTH_REQUIRED = missing key; COOLDOWN = backoff), `research-status` |
| Run status `OFFLINE` | `NETWORK_MODE=offline` is set — intended for offline/demo use |
| A job shows UNKNOWN fields | The posting does not state them; UNKNOWN is never guessed |
| Decision looks wrong | `job ID` shows every reason/risk; rate it: `feedback job ID --rating bad --reason "…"` |
| Weights never change | By design until ≥ 50 outcomes and your approval — see docs/LEARNING_LOOP.md |
| Config error | `config --validate` |
