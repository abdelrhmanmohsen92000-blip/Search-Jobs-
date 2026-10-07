"""V1.4 networking engine, application pipeline/packets, V1.5 notifications, and the synthetic demo.

All data is synthetic and lives in the per-test workspace (tests/conftest.py).
No network access: NETWORK_MODE is forced offline by the demo seeder.
"""
import datetime as _dt
import json

import pytest

from scripts import demo
from scripts.intelligence import application_pipeline as ap
from scripts.intelligence import career_data, networking_engine as ne, notifications as nt
from scripts.lib import paths, storage

TODAY = _dt.date.today()


@pytest.fixture
def seeded(isolated_workspace):
    stats = demo.seed(isolated_workspace)
    jobs = {j["job_title"] + "|" + j["company"]: j for j in career_data.load_jobs()}
    return stats, jobs


def _job(jobs, title, company_part=""):
    return next(j for k, j in jobs.items() if k.startswith(title + "|") and company_part in k)


# --- demo seeding ---------------------------------------------------------------------

def test_demo_seeds_isolated_workspace_through_real_pipeline(seeded, isolated_workspace):
    stats, jobs = seeded
    assert stats["fixture_records"] == 12 and stats["jobs_inserted"] == 11 and stats["duplicates_merged"] == 1
    assert paths.WORKSPACE == isolated_workspace.resolve()
    assert all(j["company"].startswith("[SYNTHETIC]") for j in jobs.values())
    assert stats["decisions"]["APPLY_NOW"] >= 1 and stats["decisions"]["SKIP"] >= 1
    assert stats["post_processing"]["analyses_saved"] == 11


def test_demo_refuses_the_real_workspace():
    with pytest.raises(ValueError):
        demo.seed(paths.ROOT)


# --- networking engine ---------------------------------------------------------------------

def test_networking_actions_only_for_high_value_jobs(seeded):
    _, jobs = seeded
    actions = ne.load_actions()
    by_job = {}
    for a in actions:
        by_job.setdefault(a["job_id"], []).append(a)
    skip_job = _job(jobs, "Architect", "Closed Hiring")
    assert skip_job["id"] not in by_job
    top = _job(jobs, "BIM Architect", "Desert Line")
    assert top["id"] in by_job
    types = [a["contact_type"] for a in by_job[top["id"]]]
    assert types[0] == "BIM manager" and "recruiter" in types
    for a in actions:
        assert a["status"] == "SUGGESTED" and a["sent_by_system"] == "False" and a["requires_human_approval"] == "True"
        assert a["contact_type"] in ne.load_config()["contact_types"]
        assert a["reason"] and a["outreach_angle"] and a["priority"] in ("HIGH", "MEDIUM", "LOW")


def test_drafts_use_only_stored_facts(seeded):
    _, jobs = seeded
    top = _job(jobs, "BIM Architect", "Desert Line")
    a = next(a for a in ne.load_actions() if a["job_id"] == top["id"])
    draft = a["draft_message"]
    assert top["job_title"] in draft and top["company"] in draft
    assert "Hi," in draft  # no invented contact name
    assert "4 years" in draft


def test_network_first_and_project_based_contact_types():
    cfg = ne.load_config()
    nf = ne.contact_types_for({"job_title": "Senior BIM Manager"}, {"decision": "NETWORK_FIRST"}, cfg)
    assert nf[0] == "employee/referral"
    fl = ne.contact_types_for({"job_title": "Revit Modeler", "matched_modes": ["FREELANCE"]}, {"decision": "APPLY"}, cfg)
    assert fl[0] == "project manager"
    assert len(nf) <= cfg["max_actions_per_job"]


def test_known_contact_is_used_when_logged():
    contacts = [{"person": "Sara Example", "role": "BIM Manager", "company": "Acme", "profile_url": "https://x.example/sara"}]
    analysis = {"decision": "APPLY_NOW", "opportunity_score": 90, "skills_gap": {"matched": ["Revit"], "missing": []},
                "reasons": [], "requirements": {"location": "UNKNOWN"}}
    acts = ne.recommend_actions({"id": "j1", "job_title": "BIM Architect", "company": "Acme"}, analysis,
                                contacts=contacts, profile={"experience_years": 4})
    bim = next(a for a in acts if a["contact_type"] == "BIM manager")
    assert bim["known_contact"] == "Sara Example" and bim["draft_message"].startswith("Hi Sara,")


def test_manual_status_updates_keep_history_and_schedule_followup(seeded):
    a = ne.open_actions()[0]
    done = ne.update_status(a["action_id"], "done", note="sent on LinkedIn myself", today=TODAY)
    assert done["status"] == "DONE" and done["follow_up_date"] == (TODAY + _dt.timedelta(days=7)).isoformat()
    # refreshing suggestions never resets a status you set
    ne.refresh_from_jobs()
    again = next(r for r in ne.load_actions() if r["action_id"] == a["action_id"])
    assert again["status"] == "DONE" and "sent on LinkedIn myself" in again["notes"]
    assert ne.due_followups(today=TODAY + _dt.timedelta(days=8))
    with pytest.raises(ValueError):
        ne.update_status(a["action_id"], "SENT_BY_BOT")


# --- application pipeline ------------------------------------------------------------------

def test_statuses_and_derived_status(seeded):
    _, jobs = seeded
    assert ap.STATUSES == ("DISCOVERED", "VERIFIED", "ANALYZED", "SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP",
                           "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "CLOSED")
    assert ap.derived_status(_job(jobs, "BIM Coordinator")) == "ANALYZED"
    assert ap.derived_status(_job(jobs, "Architect", "Closed Hiring")) == "CLOSED"
    assert ap.derived_status({"id": "x"}) == "DISCOVERED"


def test_transitions_are_timestamped_and_set_dates(seeded):
    _, jobs = seeded
    jid = _job(jobs, "BIM Coordinator")["id"]
    ap.transition(jid, "SHORTLISTED", actor="human:test")
    ap.transition(jid, "READY", actor="human:test")
    rec = ap.transition(jid, "APPLIED", actor="human:test", today=TODAY)
    assert rec["application_date"] == TODAY.isoformat()
    assert rec["follow_up_date"] == (TODAY + _dt.timedelta(days=7)).isoformat()
    events = ap.history(jid)
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        ("ANALYZED", "SHORTLISTED"), ("SHORTLISTED", "READY"), ("READY", "APPLIED")]
    assert all(e["at"] and e["actor"] == "human:test" for e in events)
    rec = ap.transition(jid, "FOLLOW_UP", actor="human:test", today=TODAY)
    assert rec["follow_up_count"] == 1
    rec = ap.transition(jid, "REJECTED", actor="human:test", note="missing GCC experience")
    assert rec["result"] == "REJECTED" and rec["reason"] == "missing GCC experience" and rec["follow_up_date"] == ""
    with pytest.raises(ValueError):
        ap.transition(jid, "SHORTLISTED", actor="human:test")  # closed out
    assert ap.transition(jid, "SHORTLISTED", actor="human:test", force=True)["status"] == "SHORTLISTED"


def test_system_can_never_apply_on_its_own(seeded):
    _, jobs = seeded
    jid = _job(jobs, "BIM Coordinator")["id"]
    for status in ("APPLIED", "INTERVIEW", "OFFER", "REJECTED"):
        with pytest.raises(ValueError):
            ap.transition(jid, status, actor="system")
    assert ap.transition(jid, "SHORTLISTED", actor="system")["status"] == "SHORTLISTED"
    with pytest.raises(ValueError):
        ap.transition(jid, "NOT_A_STATUS", actor="human")
    with pytest.raises(KeyError):
        ap.transition("no-such-job", "SHORTLISTED", actor="human")


def test_board_and_funnel(seeded):
    _, jobs = seeded
    demo.simulate_activity([{**career_data.to_opportunity(j), "decision": j["decision"],
                             "opportunity_score": float(j["opportunity_score"])} for j in jobs.values()])
    board = ap.board()
    assert list(board)[:8] == ["DISCOVERED", "SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED"]
    assert sum(len(v) for v in board.values()) == len(jobs)
    assert len(board["INTERVIEW"]) == 1 and len(board["REJECTED"]) == 1
    f = ap.funnel()
    assert f["SHORTLISTED"] == 4 and f["APPLIED"] == 3 and f["INTERVIEW"] == 1 and f["REJECTED"] == 1


def test_due_followups_and_interviews(seeded):
    _, jobs = seeded
    jid = _job(jobs, "BIM Coordinator")["id"]
    ap.transition(jid, "APPLIED", actor="human:test", today=TODAY - _dt.timedelta(days=8))
    assert [a["opportunity_id"] for a in ap.due_followups(today=TODAY)] == [jid]
    ap.transition(jid, "INTERVIEW", actor="human:test")
    ap.update_fields(jid, interview_date=(TODAY + _dt.timedelta(days=2)).isoformat())
    assert ap.upcoming_interviews(today=TODAY)[0]["opportunity_id"] == jid
    with pytest.raises(ValueError):
        ap.update_fields(jid, status="OFFER")


def test_packet_never_invents_and_uses_stored_data(seeded):
    _, jobs = seeded
    top = _job(jobs, "BIM Architect", "Desert Line")
    p = ap.build_packet(top["id"])
    assert p["decision"] == "APPLY_NOW" and p["cv_version"]["id"] == "CV_BIM"
    assert p["application_url"] == "https://synthetic.example/apply/1" and p["application_url_source"] == "SOURCE"
    assert p["deadline"] == top["closing_date"] and p["requires_human_approval"] is True
    assert "Revit" in p["key_skills"]["lead_with"]
    assert p["networking_action"] and p["status"] == "ANALYZED"
    # a job without an application URL keeps it UNKNOWN
    remote = _job(jobs, "Remote Full-time BIM Architect")
    p2 = ap.build_packet(remote["id"])
    assert p2["application_url"] == "UNKNOWN" or p2["application_url_source"] == "SOURCE"
    assert p2["deadline"] in ("UNKNOWN", remote["closing_date"])
    out, _ = ap.write_packet(top["id"])
    assert out.exists() and "Nothing in this packet has been sent" in out.read_text(encoding="utf-8")


def test_cover_letter_rule():
    assert ap._cover_letter_rule("Please send a cover letter, it is required.")[0] == "REQUIRED"
    assert ap._cover_letter_rule("Attach a cover letter if you like")[0] == "MENTIONED"
    assert ap._cover_letter_rule("Apply now")[0] == "NOT_STATED"
    assert ap._cover_letter_rule("")[0] == "UNKNOWN"


def test_legacy_application_rows_still_read():
    storage.write_csv(paths.APPLICATIONS_CSV, ap.FIELDNAMES[:19], [
        {"opportunity_id": "legacy-1", "company": "Old Co", "job_title": "Architect", "status": "ACCEPTED"}])
    board = ap.board(jobs=[])
    assert board["OFFER"][0]["job_id"] == "legacy-1"


# --- notifications ---------------------------------------------------------------------------

def test_new_high_priority_job_notified_once_with_outbox(seeded, capsys):
    stats, jobs = seeded
    rows = nt.load_notifications()
    assert stats["post_processing"]["notifications"] == len(rows) >= 1
    assert all(r["event_type"] == "NEW_HIGH_PRIORITY_JOB" for r in rows)
    top = _job(jobs, "BIM Architect", "Desert Line")
    assert any(r["job_id"] == top["id"] for r in rows)
    assert not nt.notify_new_jobs([{**top, "decision": "APPLY_NOW"}])  # dedup: never twice
    eml = list((paths.OUTBOX_DIR / "email").glob("*.eml"))
    assert eml and "has NOT been sent" in eml[0].read_text(encoding="utf-8")


def test_threshold_and_disabled_events():
    cfg = nt.load_config()
    assert not nt.is_high_priority({"decision": "APPLY", "opportunity_score": 80}, cfg)
    assert nt.is_high_priority({"decision": "APPLY", "opportunity_score": 86}, cfg)
    assert nt.is_high_priority({"decision": "APPLY_NOW", "opportunity_score": 70}, cfg)
    assert not nt.is_high_priority({"decision": "SKIP", "opportunity_score": 99}, cfg)
    off = {**cfg, "events": {**cfg["events"], "OFFER": {"enabled": False}}}
    assert nt.notify("OFFER", "x", config=off) is None
    with pytest.raises(ValueError):
        nt.notify("SEND_EMAIL_TO_RECRUITER", "x")


def test_followup_interview_offer_and_source_failure_events(seeded):
    _, jobs = seeded
    jid = _job(jobs, "BIM Coordinator")["id"]
    ap.transition(jid, "APPLIED", actor="human:test", today=TODAY - _dt.timedelta(days=9))
    assert [n["event_type"] for n in nt.check_followups(today=TODAY, echo=False)] == ["APPLICATION_FOLLOWUP"]
    assert nt.check_followups(today=TODAY, echo=False) == []
    ap.transition(jid, "INTERVIEW", actor="human:test")
    assert nt.check_application_events(echo=False)[0]["event_type"] == "INTERVIEW"
    ap.transition(jid, "OFFER", actor="human:test")
    assert nt.check_application_events(echo=False)[0]["event_type"] == "OFFER"
    health = {"Some Board": {"consecutive_failures": "3", "error_type": "HTTP_ERROR", "health_state": "UNAVAILABLE"},
              "Brave Search API": {"consecutive_failures": "5", "error_type": "AUTH_REQUIRED"},
              "Fine Board": {"consecutive_failures": "0"}}
    sf = nt.check_source_failures(health=health, echo=False)
    assert [n["title"] for n in sf] == ["Source failing: Some Board"]


def test_webhook_only_when_configured_and_online(monkeypatch):
    cfg = nt.load_config()
    cfg = {**cfg, "channels": {"webhook": {"enabled": True, "url_env": "CH_TEST_HOOK"}}}
    monkeypatch.delenv("CH_TEST_HOOK", raising=False)
    assert nt.notify("WEEKLY_REPORT", "w1", config=cfg)["delivery"] == "webhook:NOT_CONFIGURED"
    monkeypatch.setenv("CH_TEST_HOOK", "https://hooks.example/abc")
    monkeypatch.setenv("NETWORK_MODE", "offline")
    assert nt.notify("WEEKLY_REPORT", "w2", config=cfg)["delivery"] == "webhook:SKIPPED_OFFLINE"
    monkeypatch.setenv("NETWORK_MODE", "local")
    sent = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        sent.append(json.loads(req.data))
        return Resp()
    n = nt.notify("WEEKLY_REPORT", "w3", body="b", config=cfg, webhook_opener=opener)
    assert n["delivery"] == "webhook:HTTP_200" and sent[0]["title"] == "w3"

    def failing(req, timeout):
        raise OSError("boom")
    assert nt.notify("WEEKLY_REPORT", "w4", config=cfg, webhook_opener=failing)["delivery"].startswith("webhook:FAILED")
    assert nt.mark_read() == 4
