"""Outcome feedback (V1.7).

    career_hunter.py feedback application JOB_ID
    career_hunter.py feedback interview   JOB_ID
    career_hunter.py feedback rejection   JOB_ID --reason="missing GCC experience"
    career_hunter.py feedback offer       JOB_ID
    career_hunter.py feedback no_response JOB_ID
    career_hunter.py feedback withdrawn   JOB_ID --reason="..."
    career_hunter.py feedback job         JOB_ID --rating good|bad --reason="..."

Every entry is appended to tracking/feedback.csv together with what the system
recommended at the time (decision, scores, model version), so the learning
loop can compare recommendation with outcome. Outcome kinds also move the
application pipeline (recorded as actor `human:feedback`); the pipeline only
moves forward, except for final outcomes (rejection/offer/withdrawn/no response).
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402

KINDS = ("application", "interview", "rejection", "offer", "no_response", "withdrawn", "job")
STATUS_FOR_KIND = {"application": "APPLIED", "interview": "INTERVIEW", "rejection": "REJECTED", "offer": "OFFER",
                   "no_response": "CLOSED", "withdrawn": "WITHDRAWN"}
OUTCOME_FOR_KIND = {"application": "APPLIED", "interview": "INTERVIEW", "rejection": "REJECTED", "offer": "OFFER",
                    "no_response": "NO_RESPONSE", "withdrawn": "WITHDRAWN"}
FINAL_KINDS = ("rejection", "offer", "no_response", "withdrawn")
RATINGS = ("good", "bad")
FIELDNAMES = ["feedback_id", "created_at", "job_id", "kind", "outcome", "reason", "rating", "note", "company",
              "job_title", "country", "decision_at_time", "opportunity_score_at_time", "overall_match_at_time",
              "confidence_at_time", "model_version", "synthetic", "actor"]


def load_feedback(csv_path=None):
    return storage.read_csv(csv_path or paths.FEEDBACK_CSV)


def record(kind, job_id, reason="", rating=None, note="", actor="human:cli", today=None, csv_path=None):
    """Records one feedback entry; returns (feedback_row, application_record_or_None)."""
    from scripts.intelligence import application_pipeline as ap, career_data, insights
    kind = (kind or "").strip().lower().replace("-", "_")
    if kind not in KINDS:
        raise ValueError(f"Unknown feedback kind {kind!r}; use one of {', '.join(KINDS)}")
    if kind == "job" and (rating or "").lower() not in RATINGS:
        raise ValueError("Job feedback needs --rating good or --rating bad")
    job = career_data.find_job(job_id)
    application = ap.get_application(job_id) if job is None else ap.get_application(job["id"])
    if job is None and application is None:
        raise KeyError(f"No job or application with id {job_id!r}")
    job_id = job["id"] if job else job_id
    analysis = career_data.analysis_for(job) if job else {}

    app_record = None
    if kind in STATUS_FOR_KIND:
        target = STATUS_FOR_KIND[kind]
        current = ap.effective_status(job, application)
        order = list(ap.STATUSES)
        moves_forward = current in ap.CLOSED_OUT or order.index(target) > order.index(current)
        if kind in FINAL_KINDS or moves_forward:
            if kind in ("interview", "offer") and current not in ("APPLIED", "FOLLOW_UP", "INTERVIEW") \
                    and current not in ap.CLOSED_OUT and target != current:
                # reaching an interview implies you applied; record that step too
                if order.index(current) < order.index("APPLIED"):
                    ap.transition(job_id, "APPLIED", actor="human:feedback", note="implied by feedback", today=today)
            note_text = reason or note or f"feedback {kind}"
            app_record = ap.transition(job_id, target, actor="human:feedback", note=note_text, force=True, today=today)
    row = {
        "feedback_id": f"fb-{_dt.datetime.now():%Y%m%d%H%M%S%f}", "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "job_id": job_id, "kind": kind, "outcome": OUTCOME_FOR_KIND.get(kind, "RATING"), "reason": reason or "",
        "rating": (rating or "").lower(), "note": note or "",
        "company": (job or application or {}).get("company"), "job_title": (job or application or {}).get("job_title"),
        "country": (job or application or {}).get("country"), "decision_at_time": analysis.get("decision") or "",
        "opportunity_score_at_time": analysis.get("opportunity_score"), "overall_match_at_time": analysis.get("overall_match"),
        "confidence_at_time": analysis.get("confidence"), "model_version": analysis.get("model_version") or "",
        "synthetic": insights.is_synthetic(job or application or {}), "actor": actor,
    }
    storage.append_csv_rows(csv_path or paths.FEEDBACK_CSV, FIELDNAMES, [row])
    return row, app_record
