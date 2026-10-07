"""CLI smoke tests for the V1.4-V1.7 commands (synthetic demo workspace, offline)."""
import json

import pytest

import career_hunter
from scripts import demo
from scripts.intelligence import application_pipeline as ap, feedback
from scripts.lib import paths


@pytest.fixture
def ws(isolated_workspace, monkeypatch):
    monkeypatch.setenv("NETWORK_MODE", "offline")
    demo.seed(isolated_workspace, with_activity=True)
    return isolated_workspace


def run(capsys, *argv):
    code = career_hunter.main(list(argv))
    return code, capsys.readouterr().out


def _first_id(capsys, *filters):
    _, out = run(capsys, "jobs", "--json", *filters)
    return json.loads(out)[0]["id"]


def test_global_workspace_flag(isolated_workspace, capsys, tmp_path, monkeypatch):
    target = tmp_path / "other_ws"
    demo.init_workspace(target)
    monkeypatch.setenv("NETWORK_MODE", "offline")
    run(capsys, "--workspace", str(target), "demo")
    assert paths.WORKSPACE == target.resolve()
    _, out = run(capsys, "--workspace", str(target), "jobs")
    assert "11 of 11 jobs" in out


def test_jobs_and_job(ws, capsys):
    _, out = run(capsys, "jobs", "--country", "saudi", "--min-score", "70")
    assert "Saudi Arabia" in out and "UNKNOWN" not in out.split("\n", 1)[1]
    jid = _first_id(capsys)
    _, out = run(capsys, "job", jid[:6])
    for section in ("WHY", "RISKS", "RECOMMENDATION", "DIMENSIONS", "SKILLS GAP", "REQUIREMENTS"):
        assert section in out
    assert run(capsys, "job", "zzzz")[0] == 1


def test_companies_and_company(ws, capsys):
    _, out = run(capsys, "companies")
    assert "GRADE" in out and "[SYNTHETIC] Desert Line Architects" in out
    _, out = run(capsys, "company", "synthetic-desert-line-architects")
    assert "hiring_trend" in out and "JOBS" in out
    _, out = run(capsys, "company", "[SYNTHETIC] Desert Line Architects")
    assert "synthetic-desert-line-architects" in out


def test_applications_board_packet_and_moves(ws, capsys):
    _, out = run(capsys, "applications")
    assert "DISCOVERED" in out and "INTERVIEW (1)" in out
    jid = _first_id(capsys, "--status", "ANALYZED")
    _, out = run(capsys, "application", jid, "--status", "shortlisted", "--note", "cli")
    assert "now SHORTLISTED" in out and ap.history(jid)[-1]["actor"] == "human:cli"
    _, out = run(capsys, "application", jid)
    assert "# Application packet" in out and "Status history" in out
    _, out = run(capsys, "application", jid, "--write")
    assert (paths.REPORTS_DIR / "packets" / f"{jid}.md").exists()
    _, out = run(capsys, "application", jid, "--status", "REJECTED")
    assert run(capsys, "application", jid, "--status", "READY")[0] == 1
    _, out = run(capsys, "applications", "--list")
    assert "@" in out


def test_networking_commands(ws, capsys):
    _, out = run(capsys, "networking")
    assert "drafts only" in out and "SUGGESTED" in out
    action_id = next(line.split()[2] for line in out.splitlines() if line.strip().startswith("[HIGH"))
    _, out = run(capsys, "networking", "--show", action_id)
    assert "DRAFT (review and send it yourself)" in out
    _, out = run(capsys, "networking", "--done", action_id)
    assert "DONE" in out and "follow-up" in out
    _, out = run(capsys, "networking", "--refresh")
    assert "suggested" in out


def test_feedback_and_learning_commands(ws, capsys):
    jid = _first_id(capsys, "--status", "ANALYZED")
    _, out = run(capsys, "feedback", "rejection", jid, "--reason=missing GCC experience")
    assert "Feedback recorded: rejection" in out and "REJECTED" in out
    assert feedback.load_feedback()[-1]["reason"] == "missing GCC experience"
    _, out = run(capsys, "feedback", "job", jid, "--rating", "good")
    assert "Feedback recorded: job" in out
    assert run(capsys, "feedback", "offer", "nope")[0] == 1
    _, out = run(capsys, "learning", "evaluate")
    assert "INSUFFICIENT_DATA" in out and "/50 outcomes" in out
    _, out = run(capsys, "learning")
    assert "learning_loop" in out and "response_rate" in out
    _, out = run(capsys, "learning", "suggestions")
    assert "No learning suggestions" in out
    with pytest.raises(SystemExit):
        career_hunter.main(["learning", "approve"])


def test_reports_skills_market(ws, capsys):
    _, out = run(capsys, "report", "daily")
    assert "# Daily Career Brief" in out and (paths.REPORTS_DIR / "daily_brief.md").exists()
    _, out = run(capsys, "report", "weekly")
    assert "Weekly Market report" in out and "Weekly Skills report" in out
    _, out = run(capsys, "skills")
    assert "PRIORITY LEARNING" in out
    _, out = run(capsys, "market")
    assert "BY COUNTRY" in out and "POSTED SALARIES" in out
    _, out = run(capsys, "market", "--json")
    assert "demand_signals_v14" in json.loads(out)


def test_schedule_notifications_config_dashboard(ws, capsys):
    _, out = run(capsys, "schedule", "list")
    assert "daily_research" in out and "Africa/Cairo" in out
    _, out = run(capsys, "schedule", "run", "daily_report")
    assert "daily_report: OK" in out
    _, out = run(capsys, "schedule", "cron")
    assert "schedule run-due" in out
    _, out = run(capsys, "schedule", "run-due", "--dry-run")
    assert out.strip()
    _, out = run(capsys, "notifications", "--all")
    assert "NEW_HIGH_PRIORITY_JOB" in out
    _, out = run(capsys, "config")
    assert "Validation:       OK" in out and "never printed" in out
    assert run(capsys, "config", "--validate")[0] == 0
    assert run(capsys, "config", "--model-version", "9.9")[0] == 1
    assert run(capsys, "dashboard", "--check")[0] == 0


def test_research_dry_run_and_status_offline(ws, capsys):
    _, out = run(capsys, "research", "--dry-run")
    assert "DRY_RUN" in out and "OFFLINE" in out
    _, out = run(capsys, "research")
    assert "Requests made: 0" in out
    _, out = run(capsys, "research-status")
    assert "status=OFFLINE" in out
    _, out = run(capsys, "source-health")
    assert "SOURCE" in out
    _, out = run(capsys, "sources")
    assert "IMPLEMENTATION" in out
