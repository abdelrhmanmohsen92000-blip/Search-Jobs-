# Dashboard (V1.6)

```bash
python career_hunter.py dashboard                     # http://127.0.0.1:8765
python career_hunter.py dashboard --port 9000
python career_hunter.py --workspace demo_workspace dashboard
python career_hunter.py dashboard --check             # verify the API without starting a server
```

A single page served by the Python standard library (`scripts/dashboard/server.py`) — no build
step, no external scripts or fonts, no internet needed. It binds to `127.0.0.1` by default.

## Sections

| Section | What you can do |
|---|---|
| Overview | Hero count of APPLY NOW jobs, tiles (active, pipeline, interviews, follow-ups, networking, unread notifications), decision chart, top opportunities, follow-ups, interviews, notifications (mark read), market signals, skill gaps. A banner flags SYNTHETIC data and offline mode. |
| Jobs | Filters in one row: search, country, city, role, company, employment type, remote, freshness, status, decision, minimum score; sort by opportunity/match/confidence/dates/company/title, either order. Filters live in the URL, so a filtered view can be bookmarked. Click a row for the job detail. |
| Job detail | Decision with icon + label, scores, reasons, risks, recommendation, the 12 dimensions, skills gap (✓ matched / ≈ transferable / ✗ missing), application packet (apply URL, deadline, CV, portfolio, cover letter, skills), pipeline (move + history), outcome buttons (applied, interview, rejected, offer, no response, withdrew, good/bad match), networking drafts (copy / approve / “I sent it” / reply / no response / dismiss), extracted requirements with provenance, posting text. |
| Opportunities | Active APPLY_NOW / APPLY / NETWORK_FIRST / REVIEW jobs grouped by decision. |
| Companies | Grade, score, active jobs, trend, average match; company detail with observed facts, jobs and networking. |
| Applications | Kanban board: DISCOVERED, SHORTLISTED, READY, APPLIED, FOLLOW_UP, INTERVIEW, OFFER, REJECTED. Drag a card or use its “Move to…” menu; every move is saved to `tracking/applications.csv` + `tracking/application_events.csv` (actor `human:dashboard`). Reopening a closed-out card asks for confirmation. Application funnel and recent moves. |
| Networking | Follow-ups due and suggested actions with drafts. Nothing is ever sent. |
| Interviews | Upcoming interviews, interview funnel (applied → interview → offer), offers. |
| Skills | Skill demand chart (you have it / transferable / missing), priority learning table. |
| Market | Signals, opportunity score distribution, jobs by country / role / company (click a bar to filter Jobs), jobs found per week, employment types, posted salaries (stated only), top companies. |
| Sources | Health by state, per-source table, recent research runs, registry with credential status. |
| Settings | Workspace, network mode, environment variables (set / not set — values never shown), schedules with next/last run, decision-model versions, learning-loop status and suggestions (with the CLI commands to approve/reject), notification channels, the list of actions that always need you. |

## Charts

Inline SVG drawn at the container's real width, one hue for single-series charts, a legend when
color carries meaning (skills chart), value labels at the bar ends, hover/focus tooltips, and a
“Show table” view under every chart. Light and dark themes follow the system setting, with a
manual toggle in the sidebar.

## API

`scripts/dashboard/api.py` is a pure function `handle(method, path, query, body)` — the same
data the CLI uses (`scripts/intelligence/insights.py`).

| Method | Path | |
|---|---|---|
| GET | `/api/overview`, `/api/jobs?…filters`, `/api/jobs/<id>`, `/api/opportunities`, `/api/companies`, `/api/companies/<id>`, `/api/applications`, `/api/networking`, `/api/interviews`, `/api/skills`, `/api/market`, `/api/sources`, `/api/settings`, `/api/notifications` | read |
| POST | `/api/applications/<job_id>/move` `{status, note, force}` | pipeline move |
| POST | `/api/networking/<action_id>/status` `{status, note}` | your manual update |
| POST | `/api/feedback` `{kind, job_id, reason, rating}` | outcome feedback |
| POST | `/api/notifications/read` `{notification_id?}` | mark read |

POST requests must send the header `X-Career-Hunter: 1` (the UI does); other websites open in
your browser cannot. There is deliberately no endpoint that applies, sends, contacts anyone or
approves a learning suggestion.

## Security notes

- Default bind address is localhost. Use `--host 0.0.0.0` only on a trusted network; the
  dashboard has no login.
- All job/company text is rendered as text (never as HTML), and links are limited to http/https.
- Static files are served only from `scripts/dashboard/static/`.
