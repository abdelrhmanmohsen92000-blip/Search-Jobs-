"""V1.7 feedback and the versioned learning loop. Synthetic data only, offline."""
import datetime as _dt
import json

import pytest

from scripts import demo
from scripts.intelligence import application_pipeline as ap
from scripts.intelligence import career_data, feedback, learning_loop as ll, scoring_model
from scripts.lib import paths

TODAY = _dt.date.today()


@pytest.fixture
def seeded(isolated_workspace):
    demo.seed(isolated_workspace)
    return {j["job_title"]: j for j in career_data.load_jobs()}


def test_feedback_kinds_record_recommendation_and_move_pipeline(seeded):
    job = seeded["BIM Coordinator"]
    row, rec = feedback.record("application", job["id"])
    assert rec["status"] == "APPLIED" and row["outcome"] == "APPLIED"
    assert row["decision_at_time"] == job["decision"] and row["model_version"] == "1.0" and row["synthetic"] is True
    row, rec = feedback.record("interview", job["id"])
    assert rec["status"] == "INTERVIEW"
    row, rec = feedback.record("rejection", job["id"], reason="missing GCC experience")
    assert rec["status"] == "REJECTED" and rec["reason"] == "missing GCC experience"
    actors = {e["actor"] for e in ap.history(job["id"])}
    assert actors == {"human:feedback"}
    assert [f["kind"] for f in feedback.load_feedback()] == ["application", "interview", "rejection"]


def test_interview_feedback_implies_applied_and_never_moves_backwards(seeded):
    job = seeded["Interior Designer"]
    feedback.record("interview", job["id"])
    assert [e["to_status"] for e in ap.history(job["id"])] == ["APPLIED", "INTERVIEW"]
    _, rec = feedback.record("application", job["id"])  # late "I applied": no backwards move
    assert rec is None and ap.get_application(job["id"])["status"] == "INTERVIEW"
    _, rec = feedback.record("offer", job["id"])
    assert rec["status"] == "OFFER"


def test_job_feedback_needs_rating_and_does_not_touch_pipeline(seeded):
    job = seeded["Landscape Designer"]
    with pytest.raises(ValueError):
        feedback.record("job", job["id"])
    row, rec = feedback.record("job", job["id"], rating="bad", reason="not my field")
    assert rec is None and row["outcome"] == "RATING" and ap.get_application(job["id"]) is None
    with pytest.raises(ValueError):
        feedback.record("hired_by_bot", job["id"])
    with pytest.raises(KeyError):
        feedback.record("offer", "missing-id")


def test_outcomes_join_recommendation_with_result(seeded):
    a, b, c = seeded["BIM Coordinator"], seeded["Interior Designer"], seeded["Landscape Designer"]
    feedback.record("rejection", a["id"], reason="missing GCC experience")
    feedback.record("interview", b["id"])
    feedback.record("job", c["id"], rating="good")
    old = seeded["Senior BIM Manager"]
    ap.transition(old["id"], "APPLIED", actor="human:test", today=TODAY - _dt.timedelta(days=40))
    recs = {r["job_id"]: r for r in ll.outcomes()}
    assert recs[a["id"]]["outcome"] == "REJECTED" and recs[a["id"]]["label"] == 0
    assert recs[a["id"]]["reasons"] == ["missing GCC experience"]
    assert recs[b["id"]]["outcome"] == "INTERVIEW" and recs[b["id"]]["label"] == 1
    assert recs[c["id"]]["outcome"] == "RATED_GOOD" and recs[c["id"]]["source"] == "RATING"
    assert recs[old["id"]]["outcome"] == "NO_RESPONSE" and recs[old["id"]]["label"] == 0
    assert recs[a["id"]]["decision"] == a["decision"] and recs[a["id"]]["overall_match"] is not None
    assert all(r["synthetic"] for r in recs.values())


def test_below_threshold_reports_progress_and_suggests_nothing(seeded):
    feedback.record("rejection", seeded["BIM Coordinator"]["id"], reason="missing GCC experience")
    report = ll.evaluate()
    assert report["status"] == "INSUFFICIENT_DATA" and report["suggestion"] is None
    assert report["outcomes"] == 1 and report["min_outcomes"] == 50
    assert report["top_rejection_reasons"] == [("missing GCC experience", 1)]
    assert report["reason_dimension_hints"] == {"experience": 1}
    assert ll.load_suggestions() == []


def test_learning_simulation_finds_signal_and_never_changes_weights_silently(seeded):
    before = scoring_model.load_all()
    report = ll.evaluate(records=ll.synthetic_records(80))
    assert report["status"] == "SUGGESTION_CREATED"
    s = report["suggestion"]
    assert s["status"] == "PENDING_APPROVAL" and s["proposed_version"] == "1.1" and s["includes_synthetic"]
    w = s["changes"]["opportunity_weights"]
    assert sum(w.values()) == 100 and w["strategic_value"] > before["versions"]["1.0"]["opportunity_weights"]["strategic_value"]
    assert report["backtest"]["auc_proposed"] >= report["backtest"]["auc_current"]
    assert scoring_model.load_all() == before  # evaluation alone changed nothing
    assert [x["suggestion_id"] for x in ll.load_suggestions()] == [s["suggestion_id"]]


def test_approval_creates_new_version_and_is_reversible(seeded):
    s = ll.evaluate(records=ll.synthetic_records(80))["suggestion"]
    approved, model = ll.approve(s["suggestion_id"], approved_by="human:test")
    assert approved["status"] == "APPROVED" and model["derived_from"] == "1.0"
    assert scoring_model.active_model()["version"] == "1.0"  # added, not activated
    assert "1.1" in scoring_model.load_all()["versions"]
    with pytest.raises(ValueError):
        ll.approve(s["suggestion_id"])  # only once
    scoring_model.set_active("1.1")
    assert scoring_model.active_model()["opportunity_weights"] == s["changes"]["opportunity_weights"]
    # new analyses carry the new version; switching back is one command
    job = next(iter(seeded.values()))
    assert career_data.analysis_for({**job, "id": "fresh-id"})["model_version"] == "1.1"
    scoring_model.set_active("1.0")
    assert scoring_model.active_model()["version"] == "1.0"


def test_synthetic_suggestion_never_reaches_the_real_model(seeded, monkeypatch, tmp_path):
    s = ll.evaluate(records=ll.synthetic_records(80))["suggestion"]
    real_copy = tmp_path / "real_model.yaml"
    real_copy.write_text((paths.CONFIG_DIR / "scoring_model.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(scoring_model, "MODEL_PATH", real_copy)
    with pytest.raises(ValueError, match="SYNTHETIC"):
        ll.approve(s["suggestion_id"], model_path=real_copy)
    assert "1.1" not in scoring_model.load_all(real_copy)["versions"]


def test_reject_and_stale_base_version(seeded):
    s1 = ll.evaluate(records=ll.synthetic_records(80))["suggestion"]
    rejected = ll.reject(s1["suggestion_id"], reason="not convinced")
    assert rejected["status"] == "REJECTED"
    s2 = ll.evaluate(records=ll.synthetic_records(80, seed=11))["suggestion"]
    scoring_model.create_version("1.5", {}, "manual", "human:test", activate=True)
    with pytest.raises(ValueError, match="re-run"):
        ll.approve(s2["suggestion_id"])


def test_decision_threshold_suggestion_when_apply_now_underperforms(seeded):
    recs = ll.synthetic_records(80)
    for i, r in enumerate(recs):
        r["decision"] = "APPLY_NOW" if i % 2 else "APPLY"
        if r["decision"] == "APPLY_NOW":
            r["label"] = 1 if i % 8 == 1 else 0  # APPLY_NOW: 12.5% interview rate
        else:
            r["label"] = 1 if i % 4 == 0 else 0  # APPLY: 50%
    report = ll.evaluate(records=recs)
    rates = report["by_decision"]
    assert rates["APPLY_NOW"]["rate"] < rates["APPLY"]["rate"]
    t = report["suggestion"]["changes"]["decision_thresholds"]["apply_now"]
    assert t["opportunity"] == scoring_model.active_model()["decision_thresholds"]["apply_now"]["opportunity"] + 3
    assert any("APPLY_NOW converted worse" in r for r in report["suggestion"]["rationale"])


def test_stats_helpers():
    assert ll.auc([(1, 1), (0, 0)]) == 1.0 and ll.auc([(0, 1), (1, 0)]) == 0.0 and ll.auc([(1, 1)]) is None
    assert ll._rescale({"a": 1, "b": 1, "c": 1}) in ({"a": 34, "b": 33, "c": 33}, {"a": 33, "b": 34, "c": 33},
                                                     {"a": 33, "b": 33, "c": 34})
    assert ll._effect([1, 2, 3], [1, 2, 3]) == 0
    assert ll._next_version("1.0", {"1.0": {}, "1.1": {}}) == "1.2"
    json.dumps(ll.synthetic_records(3))


def test_reanalyze_applies_the_active_model_to_stored_jobs(seeded):
    from scripts.intelligence import post_research
    s = ll.evaluate(records=ll.synthetic_records(80))["suggestion"]
    ll.approve(s["suggestion_id"], activate=True)
    changed = post_research.reanalyze()
    assert len(changed) == len(seeded) and {c["model_version"] for c in changed} == {"1.1"}
    assert {j["model_version"] for j in career_data.load_jobs()} == {"1.1"}
    history = [r for r in __import__("scripts.lib.storage", fromlist=["x"]).read_csv(paths.ANALYSES_CSV)]
    assert {r["model_version"] for r in history} == {"1.0", "1.1"}  # old analyses stay explainable
