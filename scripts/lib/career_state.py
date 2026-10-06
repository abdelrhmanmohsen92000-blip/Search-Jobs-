"""Career Search Modes Engine (Phase 4.1).

The user's job-search objective changes over time (currently prioritizing
FULL_TIME while periodically checking FREELANCE/CONTRACT/REMOTE, say) —
config/career_state.yaml records that as data, not code, so none of it is
hard-coded into the pipeline:

    CAREER STATE -> CURRENT PRIMARY GOAL -> SEARCH MODES -> MODE PRIORITY ->
    SEARCH FREQUENCY -> MODE-SPECIFIC QUERY GENERATION -> SOURCE ROUTING ->
    JOB ACQUISITION -> NORMALIZATION -> SCORING

This module only answers "which modes are active, and which are due to run
right now" — scripts/career_search_modes.py uses it to drive the existing
scripts.search_config / scripts.daily_research pipeline per mode, never
duplicating that pipeline's own mechanics.
"""
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths  # noqa: E402
from scripts.lib.config import _load_yaml  # noqa: E402

PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
FREQUENCY_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def load_career_state(path=None):
    path = path or paths.CAREER_STATE
    if not path.exists():
        return {}
    return _load_yaml(path)


def primary_goal(state=None):
    state = state if state is not None else load_career_state()
    return state.get("current_primary_goal")


def active_modes(state=None):
    """Enabled search modes from config/career_state.yaml, sorted HIGH to
    LOW priority. Each entry: {name, priority, frequency, employment_types,
    freelance_only}. A mode missing `enabled: true` is never included — an
    absent/malformed mode is simply inactive, never a crash.
    """
    state = state if state is not None else load_career_state()
    modes = state.get("search_modes") or {}
    out = []
    for name, cfg in modes.items():
        cfg = cfg or {}
        if not cfg.get("enabled", False):
            continue
        out.append({
            "name": name,
            "priority": (cfg.get("priority") or "LOW").upper(),
            "frequency": (cfg.get("frequency") or "weekly").lower(),
            "employment_types": cfg.get("employment_types") or [],
            "freelance_only": bool(cfg.get("freelance_only", False)),
        })
    out.sort(key=lambda m: PRIORITY_RANK.get(m["priority"], 9))
    return out


def load_mode_runs(path=None):
    path = path or paths.CAREER_MODE_RUNS
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def record_mode_run(mode_name, now=None, path=None):
    path = path or paths.CAREER_MODE_RUNS
    now = now or _dt.datetime.now()
    runs = load_mode_runs(path)
    runs[mode_name] = now.isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    return runs


def due_modes(modes=None, now=None, runs=None):
    """Of the active modes, which are due to run again per their configured
    frequency. A mode never run before is always due. Conservative on bad
    data: an unparseable last-run timestamp counts as due rather than
    silently skipped forever.
    """
    modes = modes if modes is not None else active_modes()
    now = now or _dt.datetime.now()
    runs = runs if runs is not None else load_mode_runs()

    due = []
    for mode in modes:
        last_run = runs.get(mode["name"])
        if not last_run:
            due.append(mode)
            continue
        try:
            last_dt = _dt.datetime.fromisoformat(last_run)
        except ValueError:
            due.append(mode)
            continue
        days_elapsed = (now - last_dt).days
        if days_elapsed >= FREQUENCY_DAYS.get(mode["frequency"], 7):
            due.append(mode)
    return due
