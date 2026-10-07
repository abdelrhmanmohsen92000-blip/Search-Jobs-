#!/usr/bin/env python3
"""Scheduler (V1.5): config-driven recurring automation.

    config/schedules.yaml   jobs, 5-field cron expressions, timezone (default Africa/Cairo,
                            overridable with CAREER_HUNTER_TIMEZONE — never hardcoded)
    data/schedule_state.json  last run / status per job (in the active workspace)
    data/schedule_log.jsonl   one line per task run

Drivers (all call the same `run_due`):
    system cron / Task Scheduler -> `career_hunter.py schedule run-due` every 15 minutes
    local loop                   -> `career_hunter.py schedule daemon`
    cloud scheduler / routine    -> `career_hunter.py schedule run-due`

Tasks only research, analyze, report and notify you. None of them applies to a
job, sends a message, or contacts anyone.
"""
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from scripts.lib import paths, runtime  # noqa: E402

CONFIG_PATH = paths.CONFIG_DIR / "schedules.yaml"
DEFAULT_TIMEZONE = "Africa/Cairo"
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


# --- config & cron ---------------------------------------------------------------

def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def timezone_name(config=None):
    config = config if config is not None else load_config()
    return os.environ.get("CAREER_HUNTER_TIMEZONE") or config.get("timezone") or DEFAULT_TIMEZONE


def timezone(config=None):
    return ZoneInfo(timezone_name(config))


def _parse_field(text, lo, hi):
    values = set()
    for part in str(text).split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
            if step < 1:
                raise ValueError(f"Bad cron step in {text!r}")
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(part)
            end = hi if step > 1 else start
        if not (lo <= start <= hi and lo <= end <= hi and start <= end):
            raise ValueError(f"Cron value out of range in {text!r}")
        values.update(range(start, end + 1, step))
    return values


class Cron:
    """Minimal standard 5-field cron (no @aliases)."""

    def __init__(self, expression):
        fields = str(expression).split()
        if len(fields) != 5:
            raise ValueError(f"Cron expression needs 5 fields: {expression!r}")
        self.expression = expression
        self.minute, self.hour, self.dom, self.month, dow = (
            _parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _FIELD_RANGES))
        self.dow = {d % 7 for d in dow}
        self.dom_any, self.dow_any = fields[2] == "*", fields[4] == "*"

    def matches(self, dt):
        if dt.minute not in self.minute or dt.hour not in self.hour or dt.month not in self.month:
            return False
        dom_ok = dt.day in self.dom
        dow_ok = (dt.isoweekday() % 7) in self.dow
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow_ok
        if self.dow_any:
            return dom_ok
        return dom_ok or dow_ok  # standard cron: either restricted field may match

    def previous(self, now, max_minutes=40 * 1440):
        t = now.replace(second=0, microsecond=0)
        for _ in range(int(max_minutes) + 1):
            if self.matches(t):
                return t
            t -= _dt.timedelta(minutes=1)
        return None

    def next(self, after, max_days=400):
        t = after.replace(second=0, microsecond=0) + _dt.timedelta(minutes=1)
        for _ in range(max_days * 1440):
            if self.matches(t):
                return t
            t += _dt.timedelta(minutes=1)
        return None


def jobs(config=None):
    config = config if config is not None else load_config()
    out = []
    for job_id, spec in (config.get("jobs") or {}).items():
        Cron(spec["cron"])  # validate early
        if spec.get("task") not in TASKS:
            raise ValueError(f"Schedule {job_id}: unknown task {spec.get('task')!r}; known: {', '.join(TASKS)}")
        out.append({"id": job_id, "cron": spec["cron"], "task": spec["task"], "enabled": spec.get("enabled", True),
                    "description": spec.get("description", "")})
    return out


# --- state ---------------------------------------------------------------------------

def load_state():
    return json.loads(paths.SCHEDULE_STATE.read_text(encoding="utf-8")) if paths.SCHEDULE_STATE.exists() else {}


def save_state(state):
    paths.SCHEDULE_STATE.parent.mkdir(parents=True, exist_ok=True)
    paths.SCHEDULE_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _log(entry):
    log = paths.DATA_DIR / "schedule_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def status(now=None, config=None):
    config = config if config is not None else load_config()
    tz = timezone(config)
    now = (now or _dt.datetime.now(tz)).astimezone(tz)
    state = load_state()
    due = {j["id"] for j in due_jobs(now, config, state)}
    rows = []
    for job in jobs(config):
        cron = Cron(job["cron"])
        last = state.get(job["id"]) or {}
        rows.append({**job, "timezone": tz.key, "next_run": cron.next(now).isoformat() if job["enabled"] else None,
                     "last_run": last.get("last_run"), "last_status": last.get("status"), "due": job["id"] in due})
    return rows


def due_jobs(now=None, config=None, state=None):
    config = config if config is not None else load_config()
    tz = timezone(config)
    now = (now or _dt.datetime.now(tz)).astimezone(tz)
    state = load_state() if state is None else state
    catch_up = _dt.timedelta(hours=float(config.get("catch_up_hours", 12)))
    due = []
    for job in jobs(config):
        if not job["enabled"]:
            continue
        fired = Cron(job["cron"]).previous(now, max_minutes=catch_up.total_seconds() // 60)
        if fired is None or now - fired > catch_up:
            continue
        last = (state.get(job["id"]) or {}).get("last_run")
        if last and _dt.datetime.fromisoformat(last).astimezone(tz) >= fired:
            continue
        due.append({**job, "scheduled_for": fired.isoformat()})
    return due


# --- tasks -------------------------------------------------------------------------

def task_research():
    from scripts import research
    from scripts.intelligence import notifications
    snap = research.run_research()
    failures = notifications.check_source_failures()
    return {"run_id": snap.get("run_id"), "status": snap.get("status"),
            "new_opportunities": snap.get("new_opportunities", snap.get("new_jobs")),
            "network_mode": runtime.network_mode(), "source_failure_notifications": len(failures)}


def _report_task(kind, notify_weekly=False):
    def run():
        from scripts.intelligence import briefs, notifications
        path, data = briefs.write_report(kind)
        result = {"report": str(path)}
        if notify_weekly:
            n = notifications.notify("WEEKLY_REPORT", f"Weekly report ready: {path.name}", f"Open {path}",
                                     dedup_key=f"{kind}|{data.get('week')}")
            result["notified"] = bool(n)
        return result
    return run


def task_application_followup():
    from scripts.intelligence import notifications
    return {"followups": len(notifications.check_application_followups()),
            "interview_offer": len(notifications.check_application_events())}


def task_networking_followup():
    from scripts.intelligence import networking_engine, notifications
    refreshed = networking_engine.refresh_from_jobs()
    return {"followups": len(notifications.check_networking_followups()), "suggestions": refreshed}


def task_company_monitoring():
    from scripts.intelligence import company_intel
    from scripts.lib import storage
    result = {}
    if runtime.is_offline():
        result["career_pages"] = "SKIPPED (NETWORK_MODE=offline)"
    else:
        from scripts.sources import company_careers
        checked = company_careers.run_configured_company_sources()
        result["career_pages"] = {r.source: r.status for r in checked}
    index = company_intel.build_company_index()
    storage.save_json(paths.DATA_DIR / "company_index.json", company_intel.ranked(index))
    result["companies"] = len(index)
    result["a_grade"] = sum(1 for c in index.values() if c["grade"] in ("A+", "A"))
    return result


TASKS = {
    "research": task_research,
    "daily_report": _report_task("daily"),
    "application_followup": task_application_followup,
    "networking_followup": task_networking_followup,
    "weekly_market_report": _report_task("weekly_market", notify_weekly=True),
    "weekly_skills_report": _report_task("weekly_skills", notify_weekly=True),
    "company_monitoring": task_company_monitoring,
}


def run_job(job_id, config=None, now=None, dry_run=False, tasks=None):
    config = config if config is not None else load_config()
    tasks = tasks or TASKS
    job = next((j for j in jobs(config) if j["id"] == job_id or j["task"] == job_id), None)
    if job is None:
        raise KeyError(f"No scheduled job {job_id!r}")
    tz = timezone(config)
    started = (now or _dt.datetime.now(tz)).astimezone(tz)
    entry = {"job": job["id"], "task": job["task"], "started_at": started.isoformat(), "workspace": str(paths.WORKSPACE)}
    if dry_run:
        return {**entry, "status": "DRY_RUN", "summary": f"would run task {job['task']}"}
    try:
        entry["summary"] = tasks[job["task"]]()
        entry["status"] = "OK"
    except Exception as exc:  # one failing task never stops the others; it is recorded
        entry["status"] = "FAILED"
        entry["summary"] = f"{type(exc).__name__}: {exc}"
    entry["finished_at"] = _dt.datetime.now(tz).isoformat()
    state = load_state()
    state[job["id"]] = {"last_run": started.isoformat(), "status": entry["status"], "finished_at": entry["finished_at"]}
    save_state(state)
    _log(entry)
    return entry


def run_due(now=None, config=None, dry_run=False, tasks=None):
    config = config if config is not None else load_config()
    return [run_job(j["id"], config, now=now, dry_run=dry_run, tasks=tasks) for j in due_jobs(now, config)]


def daemon(interval_seconds=60, max_loops=None, sleep=time.sleep, echo=print):
    """Local scheduler loop. Ctrl+C to stop."""
    loops = 0
    echo(f"Career Hunter scheduler running (timezone {timezone_name()}, workspace {paths.WORKSPACE}); Ctrl+C to stop.")
    try:
        while max_loops is None or loops < max_loops:
            for result in run_due():
                echo(f"{result['started_at']} {result['job']}: {result['status']} {result.get('summary')}")
            loops += 1
            if max_loops is None or loops < max_loops:
                sleep(interval_seconds)
    except KeyboardInterrupt:
        echo("Scheduler stopped.")
    return loops


def crontab_text(config=None, python=None):
    config = config if config is not None else load_config()
    python = python or sys.executable or "python3"
    ws = "" if paths.WORKSPACE == paths.ROOT else f" --workspace {paths.WORKSPACE}"
    log = paths.DATA_DIR / "scheduler.log"
    base = f"cd {paths.ROOT} && {python} career_hunter.py{ws}"
    lines = ["# Career Hunter schedule — generated by `career_hunter.py schedule cron`",
             "# Option A (recommended): one entry; schedules and timezone stay in config/schedules.yaml.",
             f"*/15 * * * * {base} schedule run-due >> {log} 2>&1", "",
             "# Option B: one entry per job (requires a cron that honours CRON_TZ, e.g. cronie).",
             f"CRON_TZ={timezone_name(config)}"]
    for job in jobs(config):
        prefix = "" if job["enabled"] else "# (disabled) "
        lines.append(f"{prefix}{job['cron']} {base} schedule run {job['id']} >> {log} 2>&1")
    return "\n".join(lines) + "\n"
