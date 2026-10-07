"""V1.5 scheduler, daily brief and weekly reports. Offline, synthetic data only."""
import datetime as _dt
from zoneinfo import ZoneInfo

import pytest

from scripts import demo, scheduler
from scripts.intelligence import briefs, insights, notifications
from scripts.lib import paths

CAIRO = ZoneInfo("Africa/Cairo")


@pytest.fixture
def seeded(isolated_workspace, monkeypatch):
    monkeypatch.setenv("NETWORK_MODE", "offline")
    demo.seed(isolated_workspace, with_activity=True)
    return isolated_workspace


# --- cron ---------------------------------------------------------------------------

def test_cron_parsing_and_matching():
    c = scheduler.Cron("15 8 * * *")
    assert c.matches(_dt.datetime(2026, 10, 7, 8, 15)) and not c.matches(_dt.datetime(2026, 10, 7, 8, 16))
    sunday = scheduler.Cron("0 9 * * 0")
    assert sunday.matches(_dt.datetime(2026, 10, 11, 9, 0))  # 2026-10-11 is a Sunday
    assert scheduler.Cron("0 9 * * 7").matches(_dt.datetime(2026, 10, 11, 9, 0))
    assert not sunday.matches(_dt.datetime(2026, 10, 12, 9, 0))
    steps = scheduler.Cron("*/15 6-8 * * 1-5")
    assert steps.minute == {0, 15, 30, 45} and steps.hour == {6, 7, 8} and steps.dow == {1, 2, 3, 4, 5}
    both = scheduler.Cron("0 0 1 * 1")  # dom OR dow when both restricted
    assert both.matches(_dt.datetime(2026, 10, 1, 0, 0)) and both.matches(_dt.datetime(2026, 10, 5, 0, 0))
    for bad in ("0 8 * *", "61 8 * * *", "0 8 * * 9", "*/0 * * * *"):
        with pytest.raises(ValueError):
            scheduler.Cron(bad)


def test_next_and_previous():
    c = scheduler.Cron("30 7 * * 1,4")
    now = _dt.datetime(2026, 10, 7, 12, 0, tzinfo=CAIRO)  # Wednesday
    assert c.next(now) == _dt.datetime(2026, 10, 8, 7, 30, tzinfo=CAIRO)
    assert c.previous(now) == _dt.datetime(2026, 10, 5, 7, 30, tzinfo=CAIRO)


def test_shipped_schedule_is_valid_and_matches_requirements():
    cfg = scheduler.load_config()
    jobs = {j["id"]: j for j in scheduler.jobs(cfg)}
    assert jobs["daily_research"]["cron"] == "0 8 * * *" and jobs["daily_report"]["cron"] == "15 8 * * *"
    assert jobs["application_followup"]["cron"] == "0 10 * * *"
    assert jobs["weekly_market_report"]["cron"] == "0 9 * * 0"
    assert jobs["weekly_skills_gap_report"]["cron"] == "15 9 * * 0"
    assert {"networking_followup", "company_monitoring"} <= set(jobs)
    assert cfg["timezone"] == "Africa/Cairo"


def test_timezone_is_configurable(monkeypatch):
    monkeypatch.delenv("CAREER_HUNTER_TIMEZONE", raising=False)
    assert scheduler.timezone_name() == "Africa/Cairo"
    monkeypatch.setenv("CAREER_HUNTER_TIMEZONE", "Asia/Riyadh")
    assert scheduler.timezone_name() == "Asia/Riyadh"
    assert scheduler.timezone_name({"timezone": "Asia/Dubai"}) == "Asia/Riyadh"  # env wins
    monkeypatch.delenv("CAREER_HUNTER_TIMEZONE")
    assert scheduler.timezone_name({"timezone": "Asia/Dubai"}) == "Asia/Dubai"


def _cfg(**jobs):
    return {"timezone": "Africa/Cairo", "catch_up_hours": 2,
            "jobs": {k: {"cron": v, "task": "daily_report", "enabled": True} for k, v in jobs.items()}}


def test_due_logic_runs_each_fire_once_and_respects_catch_up(seeded):
    cfg = _cfg(brief="15 8 * * *")
    at = _dt.datetime(2026, 10, 7, 8, 20, tzinfo=CAIRO)
    assert [j["id"] for j in scheduler.due_jobs(at, cfg)] == ["brief"]
    calls = []
    tasks = {"daily_report": lambda: calls.append(1) or {"ok": True}}
    assert [r["status"] for r in scheduler.run_due(at, cfg, tasks=tasks)] == ["OK"]
    assert scheduler.run_due(at + _dt.timedelta(minutes=30), cfg, tasks=tasks) == []  # same fire: not again
    assert len(calls) == 1
    assert scheduler.due_jobs(_dt.datetime(2026, 10, 7, 11, 0, tzinfo=CAIRO), cfg) == []  # beyond catch-up
    assert [j["id"] for j in scheduler.due_jobs(_dt.datetime(2026, 10, 8, 8, 15, tzinfo=CAIRO), cfg)] == ["brief"]
    disabled = _cfg(brief="15 8 * * *")
    disabled["jobs"]["brief"]["enabled"] = False
    assert scheduler.due_jobs(at, disabled) == []


def test_failing_task_is_recorded_and_isolated(seeded):
    cfg = _cfg(a="0 8 * * *", b="0 8 * * *")
    cfg["jobs"]["b"]["task"] = "research"
    at = _dt.datetime(2026, 10, 7, 8, 5, tzinfo=CAIRO)

    def boom():
        raise RuntimeError("disk full")
    results = scheduler.run_due(at, cfg, tasks={"daily_report": boom, "research": lambda: {"ok": 1}})
    assert {r["job"]: r["status"] for r in results} == {"a": "FAILED", "b": "OK"}
    assert "disk full" in results[0]["summary"]
    state = scheduler.load_state()
    assert state["a"]["status"] == "FAILED" and state["b"]["status"] == "OK"
    assert (paths.DATA_DIR / "schedule_log.jsonl").read_text(encoding="utf-8").count("\n") == 2


def test_unknown_task_rejected():
    with pytest.raises(ValueError):
        scheduler.jobs({"jobs": {"x": {"cron": "0 8 * * *", "task": "apply_to_jobs"}}})


def test_dry_run_runs_nothing(seeded):
    cfg = _cfg(brief="15 8 * * *")
    r = scheduler.run_due(_dt.datetime(2026, 10, 7, 8, 20, tzinfo=CAIRO), cfg, dry_run=True)
    assert r[0]["status"] == "DRY_RUN" and scheduler.load_state() == {}


def test_real_tasks_run_offline(seeded):
    for job in ("daily_research", "daily_report", "application_followup", "networking_followup",
                "weekly_market_report", "weekly_skills_gap_report", "company_monitoring"):
        result = scheduler.run_job(job)
        assert result["status"] == "OK", (job, result)
    assert (paths.REPORTS_DIR / "daily_brief.md").exists()
    assert (paths.REPORTS_DIR / "weekly_market.md").exists() and (paths.REPORTS_DIR / "weekly_skills.md").exists()
    research = scheduler.load_state()["daily_research"]
    assert research["status"] == "OK"
    weekly = [n for n in notifications.load_notifications() if n["event_type"] == "WEEKLY_REPORT"]
    assert len(weekly) == 2
    status = scheduler.status()
    assert all(r["next_run"] for r in status)


def test_crontab_and_daemon(seeded):
    text = scheduler.crontab_text()
    assert "schedule run-due" in text and "CRON_TZ=Africa/Cairo" in text and "--workspace" in text
    assert text.count("schedule run ") == len(scheduler.jobs())
    out = []
    loops = scheduler.daemon(interval_seconds=0, max_loops=2, sleep=lambda s: None, echo=out.append)
    assert loops == 2 and "scheduler running" in out[0]


# --- reports --------------------------------------------------------------------------

def test_daily_brief_has_every_section(seeded):
    b = briefs.daily_brief()
    for key in ("new_jobs", "top_opportunities", "apply_now", "network_first", "application_followups", "interviews",
                "source_health", "skills_gaps", "market_signals"):
        assert key in b
    # the only APPLY_NOW job is already at INTERVIEW (simulated activity), so it is not "waiting to apply"
    assert b["apply_now"] == [] and [a["job_title"] for a in b["interviews"]] == ["BIM Architect"]
    from scripts.intelligence import application_pipeline as ap
    ap.transition(b["interviews"][0]["opportunity_id"], "WITHDRAWN", actor="human:test")
    other = next(v for v in insights.job_views() if v["decision"] == "APPLY" and v["status"] == "ANALYZED")
    from scripts.intelligence import analysis_engine
    a = analysis_engine.load_analysis(other["id"])
    analysis_engine.save_analysis({**a, "decision": "APPLY_NOW", "decision_icon": "🔥"})
    assert [v["id"] for v in briefs.daily_brief()["apply_now"]] == [other["id"]]
    text = briefs.render_daily_brief(b)
    for heading in ("NEW JOBS", "TOP OPPORTUNITIES", "APPLY NOW", "NETWORK FIRST", "APPLICATION FOLLOWUPS",
                    "INTERVIEWS", "SOURCE HEALTH", "SKILLS GAPS", "MARKET SIGNALS"):
        assert f"## {heading}" in text
    assert "SYNTHETIC demo jobs" in text


def test_brief_shows_due_followups(seeded):
    from scripts.intelligence import application_pipeline as ap
    jid = next(v["id"] for v in insights.job_views() if v["status"] == "APPLIED")
    ap.update_fields(jid, follow_up_date=_dt.date.today().isoformat())
    assert [a["opportunity_id"] for a in briefs.daily_brief()["application_followups"]] == [jid]


def test_weekly_reports_and_salary_honesty(seeded):
    m = briefs.weekly_market_report()
    assert m["total_jobs"] == 11 and m["by_country"] and m["week"].startswith(str(_dt.date.today().isocalendar()[0]))
    assert all(k.count("/") == 1 for k in m["posted_salaries"])
    s = briefs.weekly_skills_report()
    assert s["priority_learning"] and all(r["status"] != "MATCHED" for r in s["priority_learning"])
    assert any(r["skill"] == "Revit" and r["status"] == "MATCHED" for r in s["matched"])
    path, _ = briefs.write_report("weekly_skills")
    assert path.exists() and "Priority learning" in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        briefs.write_report("monthly")


def test_job_filters_and_sorting(seeded):
    views = insights.job_views()
    assert all(v["country"] == "Saudi Arabia" for v in insights.filter_jobs(views, country="saudi"))
    top = insights.filter_jobs(views, min_score=80)
    assert top and all(v["opportunity_score"] >= 80 for v in top)
    assert all(v["status"] == "INTERVIEW" for v in insights.filter_jobs(views, status="interview"))
    assert all(v["remote"] for v in insights.filter_jobs(views, remote="true"))
    by_company = insights.filter_jobs(views, sort="company", desc=False)
    assert [v["company"] for v in by_company] == sorted(v["company"] for v in views)
    assert insights.role_family("Senior BIM Manager") == "BIM Manager"
    assert insights.role_family("Exterior / Facade Designer") == "Exterior Designer"
