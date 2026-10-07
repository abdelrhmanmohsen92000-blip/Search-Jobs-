"""Notification abstraction (V1.5).

    notify(event) -> de-duplicate -> record in tracking/notifications.csv
                  -> deliver to each enabled channel (terminal / email outbox / webhook)

Channels are provider-neutral:
    terminal   printed to stdout
    email      an RFC 822 .eml file in data/outbox/email/ — ready to send, never sent
    webhook    JSON POST to YOUR endpoint, only when enabled in config/notifications.yaml,
               the URL env var is set, and NETWORK_MODE is not offline

Notifications go to you only. Nothing here contacts recruiters or companies.
A notification whose dedup key was already recorded is never raised again.
"""
import datetime as _dt
import hashlib
import json
import os
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import paths, runtime, storage  # noqa: E402

CONFIG_PATH = paths.CONFIG_DIR / "notifications.yaml"
EVENT_TYPES = ("NEW_HIGH_PRIORITY_JOB", "APPLICATION_FOLLOWUP", "NETWORKING_FOLLOWUP", "INTERVIEW", "OFFER",
               "SOURCE_FAILURE", "WEEKLY_REPORT")
FIELDNAMES = ["notification_id", "created_at", "event_type", "severity", "title", "body", "job_id", "dedup_key",
              "channels", "delivery", "read"]
_SEVERITY = {"NEW_HIGH_PRIORITY_JOB": "HIGH", "APPLICATION_FOLLOWUP": "MEDIUM", "NETWORKING_FOLLOWUP": "MEDIUM",
             "INTERVIEW": "HIGH", "OFFER": "HIGH", "SOURCE_FAILURE": "MEDIUM", "WEEKLY_REPORT": "LOW"}


def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_notifications(csv_path=None):
    return storage.read_csv(csv_path or paths.NOTIFICATIONS_CSV)


def _id(event_type, dedup_key):
    return hashlib.sha1(f"{event_type}|{dedup_key}".encode("utf-8")).hexdigest()[:12]


# --- channels -----------------------------------------------------------------

def _deliver_terminal(n, cfg, stream=None):
    print(f"[{n['severity']}] {n['event_type']}: {n['title']}" + (f" — {n['body']}" if n["body"] else ""),
          file=stream or sys.stdout)
    return "terminal:OK"


def _deliver_email(n, cfg):
    msg = EmailMessage()
    msg["Subject"] = f"[Career Hunter] {n['title']}"
    msg["To"] = cfg.get("to") or "UNKNOWN"
    msg["From"] = "career-hunter@localhost"
    msg["X-Career-Hunter-Event"] = n["event_type"]
    msg.set_content(f"{n['body']}\n\nEvent: {n['event_type']} · Job: {n['job_id'] or '-'} · {n['created_at']}\n"
                    "This file was prepared by Career Hunter and has NOT been sent.")
    out_dir = paths.OUTBOX_DIR / "email"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{n['notification_id']}.eml").write_text(msg.as_string(), encoding="utf-8")
    return "email:OUTBOX"


def _deliver_webhook(n, cfg, opener=None):
    url = os.environ.get(cfg.get("url_env") or "CAREER_HUNTER_WEBHOOK_URL")
    if not url:
        return "webhook:NOT_CONFIGURED"
    if runtime.is_offline():
        return "webhook:SKIPPED_OFFLINE"
    body = json.dumps({"event_type": n["event_type"], "severity": n["severity"], "title": n["title"],
                       "body": n["body"], "job_id": n["job_id"], "created_at": n["created_at"],
                       "text": f"{n['title']} — {n['body']}"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=float(cfg.get("timeout_seconds", 10))) as resp:
            return f"webhook:HTTP_{getattr(resp, 'status', 200)}"
    except Exception as exc:  # a failed webhook never breaks the run; it is recorded
        return f"webhook:FAILED({type(exc).__name__})"


def notify(event_type, title, body="", dedup_key=None, job_id=None, severity=None, config=None, csv_path=None,
           echo=True, webhook_opener=None):
    """Raises one notification. Returns the record, or None when the event type is
    disabled or the dedup key was already notified."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type {event_type!r}")
    config = config or load_config()
    if not ((config.get("events") or {}).get(event_type) or {}).get("enabled", True):
        return None
    csv_path = csv_path or paths.NOTIFICATIONS_CSV
    dedup_key = dedup_key or f"{job_id}|{title}"
    nid = _id(event_type, dedup_key)
    existing = load_notifications(csv_path)
    if any(r.get("notification_id") == nid for r in existing):
        return None
    n = {"notification_id": nid, "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
         "event_type": event_type, "severity": severity or _SEVERITY[event_type], "title": title, "body": body,
         "job_id": job_id or "", "dedup_key": dedup_key, "read": False}
    channels = config.get("channels") or {}
    delivered = []
    if (channels.get("terminal") or {}).get("enabled") and echo:
        delivered.append(_deliver_terminal(n, channels["terminal"]))
    if (channels.get("email") or {}).get("enabled"):
        delivered.append(_deliver_email(n, channels["email"]))
    if (channels.get("webhook") or {}).get("enabled"):
        delivered.append(_deliver_webhook(n, channels["webhook"], webhook_opener))
    n["channels"] = "|".join(k for k, v in channels.items() if (v or {}).get("enabled"))
    n["delivery"] = "|".join(delivered) or "RECORDED_ONLY"
    storage.append_csv_rows(csv_path, FIELDNAMES, [n])
    return n


def mark_read(notification_id=None, csv_path=None):
    csv_path = csv_path or paths.NOTIFICATIONS_CSV
    rows = load_notifications(csv_path)
    count = 0
    for r in rows:
        if notification_id in (None, r.get("notification_id")) and str(r.get("read")) != "True":
            r["read"] = True
            count += 1
    storage.write_csv(csv_path, FIELDNAMES, rows)
    return count


# --- event producers -------------------------------------------------------------

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def is_high_priority(job, config=None):
    rules = ((config or load_config()).get("events") or {}).get("NEW_HIGH_PRIORITY_JOB") or {}
    decision = job.get("decision")
    if decision in (rules.get("always_for_decisions") or []):
        return True
    return (decision in (rules.get("decisions") or [])
            and _num(job.get("opportunity_score")) >= float(rules.get("min_opportunity_score", 85)))


def notify_new_jobs(jobs, config=None, echo=True):
    config = config or load_config()
    out = []
    for j in jobs:
        if not is_high_priority(j, config):
            continue
        where = ", ".join(x for x in (j.get("city"), j.get("country")) if x) or "location UNKNOWN"
        n = notify("NEW_HIGH_PRIORITY_JOB", f"{j.get('decision')}: {j.get('job_title')} @ {j.get('company')}",
                   f"Opportunity {j.get('opportunity_score')} · {where}. Run `career_hunter.py job {j.get('id')}`.",
                   dedup_key=j.get("id"), job_id=j.get("id"), config=config, echo=echo)
        if n:
            out.append(n)
    return out


def check_followups(today=None, config=None, echo=True):
    from scripts.intelligence import application_pipeline, networking_engine
    today = today or _dt.date.today()
    out = []
    for a in application_pipeline.due_followups(today=today):
        n = notify("APPLICATION_FOLLOWUP", f"Follow up: {a.get('job_title')} @ {a.get('company')}",
                   f"Applied {a.get('application_date') or 'UNKNOWN'}; follow-up due {a.get('follow_up_date')}. "
                   "Send it yourself, then run `career_hunter.py application <id> --status FOLLOW_UP`.",
                   dedup_key=f"{a.get('opportunity_id')}|{a.get('follow_up_date')}", job_id=a.get("opportunity_id"),
                   config=config, echo=echo)
        if n:
            out.append(n)
    for r in networking_engine.due_followups(today=today):
        n = notify("NETWORKING_FOLLOWUP", f"Networking follow-up: {r.get('contact_type')} @ {r.get('company')}",
                   f"You reached out on {r.get('done_at')}; follow-up due {r.get('follow_up_date')} (draft only, you send it).",
                   dedup_key=f"{r.get('action_id')}|{r.get('follow_up_date')}", job_id=r.get("job_id"),
                   config=config, echo=echo)
        if n:
            out.append(n)
    return out


def check_application_events(config=None, echo=True):
    """INTERVIEW and OFFER notifications for applications in those states."""
    from scripts.intelligence import application_pipeline
    out = []
    for a in application_pipeline.load_applications():
        status = application_pipeline.normalize_status(a.get("status"))
        if status == "INTERVIEW":
            date = a.get("interview_date") or "UNKNOWN"
            n = notify("INTERVIEW", f"Interview: {a.get('job_title')} @ {a.get('company')}",
                       f"Interview date: {date}. Prepare with `career_hunter.py application {a.get('opportunity_id')}`.",
                       dedup_key=f"{a.get('opportunity_id')}|{date}", job_id=a.get("opportunity_id"),
                       config=config, echo=echo)
        elif status == "OFFER":
            n = notify("OFFER", f"Offer: {a.get('job_title')} @ {a.get('company')}",
                       "Record the outcome with `career_hunter.py feedback offer <id>` so the learning loop sees it.",
                       dedup_key=a.get("opportunity_id"), job_id=a.get("opportunity_id"), config=config, echo=echo)
        else:
            continue
        if n:
            out.append(n)
    return out


def check_source_failures(health=None, today=None, config=None, echo=True):
    from scripts.lib import source_health
    config = config or load_config()
    rules = (config.get("events") or {}).get("SOURCE_FAILURE") or {}
    health = source_health.load_health() if health is None else health
    today = (today or _dt.date.today()).isoformat()
    out = []
    for name, row in health.items():
        fails = int(_num(row.get("consecutive_failures")))
        if fails < int(rules.get("min_consecutive_failures", 2)):
            continue
        if (row.get("error_type") or "") in (rules.get("ignore_error_types") or []):
            continue
        n = notify("SOURCE_FAILURE", f"Source failing: {name}",
                   f"{fails} consecutive failures ({row.get('health_state') or row.get('status')}: "
                   f"{row.get('error_type') or ''}). See `career_hunter.py source-health`.",
                   dedup_key=f"{name}|{today}", config=config, echo=echo)
        if n:
            out.append(n)
    return out
