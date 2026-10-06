"""Phase 4.1 — Career Search Modes, Scheduling & Dynamic Priorities.

All tests use local fixtures (tmp_path for state/run files, monkeypatched
profile/search-matrix dicts for query generation) — no network, no reliance
on the real config/career_state.yaml beyond one smoke test that it parses.
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import career_state
from scripts.career_search_modes import run_due_modes, run_for_mode, split_limit
from scripts.search_config import build_query_plan


SAMPLE_STATE = {
    "current_primary_goal": "FULL_TIME",
    "search_modes": {
        "FULL_TIME": {"enabled": True, "priority": "HIGH", "frequency": "daily",
                      "employment_types": ["Full-time"], "freelance_only": False},
        "REMOTE": {"enabled": True, "priority": "MEDIUM", "frequency": "daily",
                   "employment_types": ["Remote"], "freelance_only": False},
        "CONTRACT": {"enabled": True, "priority": "LOW", "frequency": "weekly",
                     "employment_types": ["Contract"], "freelance_only": False},
        "PART_TIME": {"enabled": False, "priority": "LOW", "frequency": "weekly",
                      "employment_types": ["Part-time"], "freelance_only": False},
    },
}


# --- config loading / active modes ------------------------------------------

def test_real_career_state_file_parses_and_has_a_primary_goal():
    state = career_state.load_career_state()
    assert career_state.primary_goal(state) is not None
    assert career_state.active_modes(state)


def test_active_modes_excludes_disabled_modes():
    modes = career_state.active_modes(SAMPLE_STATE)
    names = {m["name"] for m in modes}
    assert "PART_TIME" not in names
    assert "FULL_TIME" in names


def test_active_modes_sorted_high_to_low_priority():
    modes = career_state.active_modes(SAMPLE_STATE)
    assert [m["name"] for m in modes] == ["FULL_TIME", "REMOTE", "CONTRACT"]


def test_missing_career_state_file_returns_empty_not_a_crash(tmp_path):
    assert career_state.load_career_state(tmp_path / "nope.yaml") == {}
    assert career_state.active_modes({}) == []


# --- due-mode scheduling -----------------------------------------------------

def test_mode_never_run_before_is_always_due():
    modes = career_state.active_modes(SAMPLE_STATE)
    due = career_state.due_modes(modes, runs={})
    assert {m["name"] for m in due} == {"FULL_TIME", "REMOTE", "CONTRACT"}


def test_daily_mode_due_again_after_one_day():
    modes = [m for m in career_state.active_modes(SAMPLE_STATE) if m["name"] == "FULL_TIME"]
    now = _dt.datetime(2026, 1, 10, 9, 0, 0)
    yesterday = (now - _dt.timedelta(days=1)).isoformat(timespec="seconds")
    due = career_state.due_modes(modes, now=now, runs={"FULL_TIME": yesterday})
    assert due == modes


def test_daily_mode_not_due_same_day():
    modes = [m for m in career_state.active_modes(SAMPLE_STATE) if m["name"] == "FULL_TIME"]
    now = _dt.datetime(2026, 1, 10, 18, 0, 0)
    earlier_today = _dt.datetime(2026, 1, 10, 9, 0, 0).isoformat(timespec="seconds")
    due = career_state.due_modes(modes, now=now, runs={"FULL_TIME": earlier_today})
    assert due == []


def test_weekly_mode_not_due_after_two_days():
    modes = [m for m in career_state.active_modes(SAMPLE_STATE) if m["name"] == "CONTRACT"]
    now = _dt.datetime(2026, 1, 10)
    two_days_ago = (now - _dt.timedelta(days=2)).isoformat(timespec="seconds")
    assert career_state.due_modes(modes, now=now, runs={"CONTRACT": two_days_ago}) == []


def test_weekly_mode_due_after_eight_days():
    modes = [m for m in career_state.active_modes(SAMPLE_STATE) if m["name"] == "CONTRACT"]
    now = _dt.datetime(2026, 1, 10)
    eight_days_ago = (now - _dt.timedelta(days=8)).isoformat(timespec="seconds")
    assert career_state.due_modes(modes, now=now, runs={"CONTRACT": eight_days_ago}) == modes


def test_unparseable_last_run_timestamp_counts_as_due():
    modes = [m for m in career_state.active_modes(SAMPLE_STATE) if m["name"] == "FULL_TIME"]
    assert career_state.due_modes(modes, runs={"FULL_TIME": "not-a-timestamp"}) == modes


def test_record_mode_run_persists_and_round_trips(tmp_path):
    run_path = tmp_path / "career_mode_runs.json"
    now = _dt.datetime(2026, 1, 1, 12, 0, 0)
    career_state.record_mode_run("FULL_TIME", now=now, path=run_path)
    runs = career_state.load_mode_runs(run_path)
    assert runs["FULL_TIME"] == now.isoformat(timespec="seconds")


def test_record_mode_run_preserves_other_modes(tmp_path):
    run_path = tmp_path / "career_mode_runs.json"
    career_state.record_mode_run("FULL_TIME", now=_dt.datetime(2026, 1, 1), path=run_path)
    career_state.record_mode_run("CONTRACT", now=_dt.datetime(2026, 1, 2), path=run_path)
    runs = career_state.load_mode_runs(run_path)
    assert "FULL_TIME" in runs and "CONTRACT" in runs


# --- priority-weighted query-budget splitting -------------------------------

def test_split_limit_weights_by_priority():
    modes = career_state.active_modes(SAMPLE_STATE)  # HIGH, MEDIUM, LOW -> weights 3:2:1
    splits = split_limit(modes, 60)
    assert splits["FULL_TIME"] > splits["REMOTE"] > splits["CONTRACT"]
    assert splits["FULL_TIME"] == 30
    assert splits["REMOTE"] == 20
    assert splits["CONTRACT"] == 10


def test_split_limit_gives_everyone_at_least_one():
    modes = career_state.active_modes(SAMPLE_STATE)
    splits = split_limit(modes, 1)
    assert all(v >= 1 for v in splits.values())


def test_split_limit_none_means_no_per_mode_cap():
    modes = career_state.active_modes(SAMPLE_STATE)
    splits = split_limit(modes, None)
    assert all(v is None for v in splits.values())


# --- query generation respects mode employment_types override --------------

def test_build_query_plan_employment_types_override(monkeypatch):
    plan = build_query_plan(region="gulf", employment_types=["Contract"], limit=10)
    assert plan
    assert all(q["employment_type"] == "Contract" for q in plan)


def test_build_query_plan_without_override_is_unchanged(monkeypatch):
    plan_default = build_query_plan(region="gulf", limit=10)
    plan_explicit_none = build_query_plan(region="gulf", limit=10, employment_types=None)
    assert {q["employment_type"] for q in plan_default} == {q["employment_type"] for q in plan_explicit_none}


def test_remote_only_still_wins_over_employment_types_override():
    plan = build_query_plan(region="gulf", remote_only=True, employment_types=["Contract"], limit=5)
    assert all(q["employment_type"] == "Remote" for q in plan)


# --- orchestrator: dry-run only, no tracker/report writes -------------------

def test_run_for_mode_dry_run_never_touches_trackers(tmp_path, monkeypatch):
    monkeypatch.setattr(career_state.paths, "CAREER_MODE_RUNS", tmp_path / "runs.json")
    mode = {"name": "CONTRACT", "priority": "LOW", "frequency": "weekly",
            "employment_types": ["Contract"], "freelance_only": False}
    result = run_for_mode(mode, region="gulf", limit=3, dry_run=True)
    assert result["dry_run"] is True
    assert result["mode"] == "CONTRACT"
    assert not (tmp_path / "runs.json").exists()  # dry run never records a mode as having run


def test_run_due_modes_reports_nothing_due_message(monkeypatch):
    monkeypatch.setattr(career_state, "active_modes", lambda state=None: [])
    outcome = run_due_modes()
    assert outcome["modes_run"] == []
    assert "message" in outcome
