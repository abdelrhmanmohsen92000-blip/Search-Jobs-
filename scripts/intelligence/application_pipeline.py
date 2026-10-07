"""Application pipeline (V1.4).

One application record per job (application id == job id) in
tracking/applications.csv, and every status change appended to
tracking/application_events.csv with a timestamp and who made it.

    DISCOVERED -> VERIFIED -> ANALYZED -> SHORTLISTED -> READY -> APPLIED ->
    FOLLOW_UP -> INTERVIEW -> OFFER          (or REJECTED / WITHDRAWN / CLOSED)

Rules:
    - the system never moves a job to APPLIED (or any later status) by itself;
      those transitions are recorded only from an explicit human command
      (CLI / dashboard) and carry the actor that made them
    - a closed-out status (REJECTED / WITHDRAWN / CLOSED) can only be reopened
      with force=True, and the reopening is recorded too
    - packets never invent an application URL, deadline, salary or cover-letter
      rule: anything not in the stored posting stays UNKNOWN
"""
import datetime as _dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import paths, storage  # noqa: E402

CONFIG_PATH = paths.CONFIG_DIR / "application.yaml"
UNKNOWN = "UNKNOWN"
STATUSES = ("DISCOVERED", "VERIFIED", "ANALYZED", "SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP", "INTERVIEW",
            "OFFER", "REJECTED", "WITHDRAWN", "CLOSED")
CLOSED_OUT = ("REJECTED", "WITHDRAWN", "CLOSED")
HUMAN_ONLY = ("APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN")
LEGACY_STATUS = {"ACCEPTED": "OFFER"}  # rows written before V1.4

# Existing tracker columns first (unchanged order), V1.4 columns appended.
FIELDNAMES = [
    "opportunity_id", "company", "job_title", "country", "source", "url", "score", "cv_version",
    "portfolio_version", "application_date", "status", "contact_person", "linkedin", "email", "follow_up_date",
    "interview_date", "result", "reason", "notes",
    "decision", "opportunity_score", "application_url", "deadline", "follow_up_count", "created_at",
    "status_updated_at",
]
EVENT_FIELDNAMES = ["event_id", "job_id", "from_status", "to_status", "at", "actor", "note"]


def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def normalize_status(status):
    s = (status or "").strip().upper().replace("-", "_").replace(" ", "_")
    return LEGACY_STATUS.get(s, s)


def load_applications(csv_path=None):
    return storage.read_csv(csv_path or paths.APPLICATIONS_CSV)


def get_application(job_id, csv_path=None):
    return next((a for a in load_applications(csv_path) if a.get("opportunity_id") == job_id), None)


def derived_status(job_row):
    """Pipeline status of a job that has no application record yet."""
    if not job_row:
        return "DISCOVERED"
    if (job_row.get("freshness") or "") == "CLOSED" or (job_row.get("lifecycle_status") or "") == "CLOSED":
        return "CLOSED"
    if job_row.get("decision"):
        return "ANALYZED"
    if job_row.get("job_page_url") or job_row.get("extraction_method"):
        return "VERIFIED"
    return "DISCOVERED"


def effective_status(job_row, application=None):
    if application and application.get("status"):
        return normalize_status(application["status"])
    return derived_status(job_row)


def _record_from_job(job_row):
    return {
        "opportunity_id": job_row.get("id"), "company": job_row.get("company"), "job_title": job_row.get("job_title"),
        "country": job_row.get("country"), "source": job_row.get("source"),
        "url": job_row.get("job_page_url") or job_row.get("source_url") or "", "score": job_row.get("score"),
        "decision": job_row.get("decision"), "opportunity_score": job_row.get("opportunity_score"),
        "application_url": job_row.get("application_url") or UNKNOWN,
        "deadline": job_row.get("closing_date") or UNKNOWN, "follow_up_count": 0, "created_at": _now(),
    }


def transition(job_id, new_status, actor="human", note="", force=False, today=None, csv_path=None, events_path=None,
               jobs=None):
    """Moves one job to `new_status`, creating its application record if needed.
    Returns the updated record. Raises ValueError on an invalid move."""
    from scripts.intelligence import career_data
    new_status = normalize_status(new_status)
    if new_status not in STATUSES:
        raise ValueError(f"Unknown status {new_status!r}; use one of {', '.join(STATUSES)}")
    if new_status in HUMAN_ONLY and not str(actor).startswith("human"):
        raise ValueError(f"{new_status} can only be set by a human (actor={actor!r})")
    csv_path = csv_path or paths.APPLICATIONS_CSV
    events_path = events_path or paths.APPLICATION_EVENTS_CSV
    stamp = _now() if today is None else f"{today.isoformat()}T12:00:00"  # explicit date: back-dated entry
    today = today or _dt.date.today()

    rows = load_applications(csv_path)
    record = next((a for a in rows if a.get("opportunity_id") == job_id), None)
    job_row = career_data.find_job(job_id, jobs)
    if record is None and job_row is None:
        raise KeyError(f"No job or application with id {job_id!r}")
    if record is None:
        record = _record_from_job(job_row)
        rows.append(record)
        job_id = job_row["id"]
    old = effective_status(job_row, record if record.get("status") else None)
    if old == new_status:
        return record
    if old in CLOSED_OUT and not force:
        raise ValueError(f"{job_id} is {old}; reopening needs force=True (--force)")

    cfg = load_config().get("follow_up") or {}
    record["status"] = new_status
    record["status_updated_at"] = stamp
    if new_status == "APPLIED" and not record.get("application_date"):
        record["application_date"] = today.isoformat()
    if new_status in ("APPLIED", "FOLLOW_UP"):
        if new_status == "FOLLOW_UP":
            record["follow_up_count"] = int(record.get("follow_up_count") or 0) + 1
        days = cfg.get("after_applied_days", 7) if new_status == "APPLIED" else cfg.get("repeat_every_days", 7)
        record["follow_up_date"] = (today + _dt.timedelta(days=int(days))).isoformat()
    if new_status == "INTERVIEW" and not record.get("interview_date"):
        record["interview_date"] = UNKNOWN  # set the real date with `application <id> --interview-date`
    if new_status in ("OFFER", "REJECTED", "WITHDRAWN", "CLOSED"):
        record["result"] = new_status
        record["follow_up_date"] = ""
    if note:
        record["notes"] = (record.get("notes") + " | " if record.get("notes") else "") + note
        if new_status in ("REJECTED", "WITHDRAWN", "CLOSED"):
            record["reason"] = note
    storage.write_csv(csv_path, FIELDNAMES, rows)
    storage.append_csv_rows(events_path, EVENT_FIELDNAMES, [{
        "event_id": f"{job_id}:{record['status_updated_at']}:{new_status}", "job_id": job_id, "from_status": old,
        "to_status": new_status, "at": record["status_updated_at"], "actor": actor, "note": note}])
    return record


def update_fields(job_id, csv_path=None, **fields):
    """Human edits to non-status fields (interview_date, contact_person, cv_version, ...)."""
    allowed = set(FIELDNAMES) - {"opportunity_id", "status", "status_updated_at", "created_at"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Cannot edit {sorted(bad)}")
    csv_path = csv_path or paths.APPLICATIONS_CSV
    rows = load_applications(csv_path)
    record = next((a for a in rows if a.get("opportunity_id") == job_id), None)
    if record is None:
        raise KeyError(f"No application for {job_id!r} — move it into the pipeline first (e.g. shortlist)")
    record.update({k: v for k, v in fields.items() if v is not None})
    storage.write_csv(csv_path, FIELDNAMES, rows)
    return record


def history(job_id, events_path=None):
    return [e for e in storage.read_csv(events_path or paths.APPLICATION_EVENTS_CSV) if e.get("job_id") == job_id]


def due_followups(applications=None, today=None):
    applications = load_applications() if applications is None else applications
    today = (today or _dt.date.today()).isoformat()
    return [a for a in applications if normalize_status(a.get("status")) in ("APPLIED", "FOLLOW_UP")
            and a.get("follow_up_date") and a["follow_up_date"] <= today]


def upcoming_interviews(applications=None, today=None):
    applications = load_applications() if applications is None else applications
    today = (today or _dt.date.today()).isoformat()
    out = []
    for a in applications:
        if normalize_status(a.get("status")) != "INTERVIEW":
            continue
        date = a.get("interview_date") or UNKNOWN
        if date == UNKNOWN or date >= today:
            out.append(a)
    return sorted(out, key=lambda a: a.get("interview_date") or "9999")


def board(jobs=None, applications=None, columns=None):
    """{column: [card]} for the Kanban view, plus "_closed" for closed-out items."""
    from scripts.intelligence import career_data
    jobs = career_data.load_jobs() if jobs is None else jobs
    applications = load_applications() if applications is None else applications
    columns = columns or load_config().get("kanban_columns") or list(STATUSES)
    apps = {a.get("opportunity_id"): a for a in applications}
    out = {c: [] for c in columns}
    out["_closed"] = []
    seen = set()
    for j in jobs:
        a = apps.get(j["id"])
        status = effective_status(j, a)
        seen.add(j["id"])
        card = {"job_id": j["id"], "job_title": j.get("job_title"), "company": j.get("company"),
                "country": j.get("country") or UNKNOWN, "status": status, "decision": j.get("decision") or "",
                "opportunity_score": career_data.num(j.get("opportunity_score")),
                "follow_up_date": (a or {}).get("follow_up_date") or "", "interview_date": (a or {}).get("interview_date") or ""}
        _place(out, card, status)
    for job_id, a in apps.items():  # applications whose job row is gone (e.g. manually logged)
        if job_id not in seen:
            status = normalize_status(a.get("status"))
            _place(out, {"job_id": job_id, "job_title": a.get("job_title"), "company": a.get("company"),
                         "country": a.get("country") or UNKNOWN, "status": status, "decision": a.get("decision") or "",
                         "opportunity_score": career_data.num(a.get("opportunity_score")),
                         "follow_up_date": a.get("follow_up_date") or "", "interview_date": a.get("interview_date") or ""},
                   status)
    for cards in out.values():
        cards.sort(key=lambda c: -(c["opportunity_score"] or 0))
    return out


def _place(out, card, status):
    if status in out:
        out[status].append(card)
    elif status in ("VERIFIED", "ANALYZED") and "DISCOVERED" in out:
        out["DISCOVERED"].append(card)
    else:
        out["_closed"].append(card)


def funnel(applications=None, events=None):
    """Counts of jobs that have EVER reached each stage (from the event log),
    so a rejection after an interview still counts as an interview."""
    applications = load_applications() if applications is None else applications
    events = storage.read_csv(paths.APPLICATION_EVENTS_CSV) if events is None else events
    reached = {}
    for a in applications:
        reached.setdefault(a.get("opportunity_id"), set()).add(normalize_status(a.get("status")))
    for e in events:
        reached.setdefault(e.get("job_id"), set()).add(normalize_status(e.get("to_status")))
    stages = ("SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED")
    after_applied = {"APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED"}
    counts = {}
    for stage in stages:
        if stage == "APPLIED":
            counts[stage] = sum(1 for s in reached.values() if s & after_applied)
        else:
            counts[stage] = sum(1 for s in reached.values() if stage in s)
    return counts


# --- packets -------------------------------------------------------------------

def _pick_version(title, versions, default):
    title = (title or "").lower()
    for v in versions or []:
        if any(k in title for k in v.get("title_keywords") or []):
            return v
    return next((v for v in versions or [] if v.get("id") == default), {"id": default or UNKNOWN})


def _cover_letter_rule(description):
    text = (description or "").lower()
    if not text:
        return UNKNOWN, "Posting text not stored"
    if re.search(r"cover letter[^.\n]{0,40}(required|must|mandatory)|(required|must|mandatory)[^.\n]{0,40}cover letter", text):
        return "REQUIRED", "The posting asks for a cover letter"
    if "cover letter" in text or "motivation letter" in text:
        return "MENTIONED", "The posting mentions a cover letter"
    return "NOT_STATED", "The posting does not mention one — a short one is still a good idea for APPLY_NOW roles"


def build_packet(job_id, jobs=None):
    """Everything needed to apply to one job, from stored data only."""
    from scripts.intelligence import career_data, company_intel, networking_engine
    from scripts.intelligence.application_strategy import combined_portfolio_evidence
    job_row = career_data.find_job(job_id, jobs)
    if job_row is None:
        raise KeyError(f"No job with id {job_id!r}")
    cfg = load_config()
    index = company_intel.build_company_index()
    company = index.get(company_intel.company_id(job_row.get("company")))
    analysis = career_data.analysis_for(job_row, company_lookup=company_intel.make_lookup(index))
    opp = career_data.to_opportunity(job_row)
    gap = analysis.get("skills_gap") or {}
    cv = _pick_version(job_row.get("job_title"), cfg.get("cv_versions"), cfg.get("default_cv"))
    portfolio = _pick_version(job_row.get("job_title"), cfg.get("portfolio_versions"), cfg.get("default_portfolio"))
    evidence = combined_portfolio_evidence(opp)
    projects = [] if evidence == "PORTFOLIO_DATA_INSUFFICIENT" else [
        {"project": e.get("project") or e.get("capability") or e.get("country"), "evidence_tier": e.get("evidence_tier"),
         "why": "; ".join(e.get("evidence") or []) if isinstance(e.get("evidence"), list) else e.get("why_relevant") or ""}
        for e in evidence if e.get("evidence_tier") == "DIRECT_PROJECT_EVIDENCE"]
    cover, cover_why = _cover_letter_rule(job_row.get("description"))
    actions = [a for a in networking_engine.load_actions() if a.get("job_id") == job_row["id"]]
    if not actions:
        actions = networking_engine.recommend_actions(opp, analysis, company)
    application = get_application(job_row["id"])
    app_url = job_row.get("application_url") or UNKNOWN
    return {
        "job": {"id": job_row["id"], "title": job_row.get("job_title"), "company": job_row.get("company"),
                "location": ", ".join(x for x in (job_row.get("city"), job_row.get("country")) if x) or UNKNOWN,
                "employment_type": job_row.get("employment_type") or UNKNOWN,
                "job_page_url": job_row.get("job_page_url") or job_row.get("source_url") or UNKNOWN},
        "company": {"company_id": (company or {}).get("company_id"), "grade": (company or {}).get("grade"),
                    "grade_label": (company or {}).get("grade_label"), "company_score": (company or {}).get("company_score")},
        "decision": analysis.get("decision"), "decision_icon": analysis.get("decision_icon"),
        "overall_match": analysis.get("overall_match"), "opportunity_score": analysis.get("opportunity_score"),
        "confidence": analysis.get("confidence"), "reasons": analysis.get("reasons"), "risks": analysis.get("risks"),
        "recommendation": analysis.get("recommendation"),
        "cv_version": {"id": cv.get("id"), "label": cv.get("label"), "file": cv.get("file", UNKNOWN),
                       "why": "Matched on job title" if cv.get("title_keywords") and any(
                           k in (job_row.get("job_title") or "").lower() for k in cv["title_keywords"]) else "Default CV"},
        "portfolio": {"id": portfolio.get("id"), "label": portfolio.get("label"), "file": portfolio.get("file", UNKNOWN),
                      "project_examples": projects or "PORTFOLIO_DATA_INSUFFICIENT"},
        "cover_letter": {"requirement": cover, "why": cover_why},
        "key_skills": {"lead_with": gap.get("matched") or [],
                       "transferable": [t["skill"] for t in gap.get("transferable") or []],
                       "do_not_claim": gap.get("missing") or []},
        "application_url": app_url,
        "application_url_source": "SOURCE" if app_url != UNKNOWN else "UNKNOWN — use the job page; never guessed",
        "networking_action": [{k: a.get(k) for k in ("action_id", "contact_type", "priority", "reason", "outreach_angle",
                                                     "status")} for a in actions],
        "deadline": job_row.get("closing_date") or UNKNOWN,
        "status": effective_status(job_row, application),
        "requires_human_approval": True,
        "model_version": analysis.get("model_version"),
    }


def packet_markdown(packet):
    p = packet
    lines = [f"# Application packet — {p['job']['title']} @ {p['job']['company']}", "",
             f"**Decision:** {p['decision_icon']} {p['decision']} · overall match {p['overall_match']} · "
             f"opportunity {p['opportunity_score']} · confidence {p['confidence']} · status {p['status']}", "",
             f"- Job page: {p['job']['job_page_url']}", f"- Apply at: {p['application_url']} ({p['application_url_source']})",
             f"- Deadline: {p['deadline']}", f"- Location: {p['job']['location']} · {p['job']['employment_type']}",
             f"- Company grade: {p['company']['grade']} {p['company']['grade_label'] or ''}", "",
             "## Why", *[f"- {r}" for r in p["reasons"]], "", "## Risks", *[f"- {r}" for r in p["risks"]], "",
             "## Documents",
             f"- CV: {p['cv_version']['id']} — {p['cv_version']['label']} (file: {p['cv_version']['file']})",
             f"- Portfolio: {p['portfolio']['id']} — {p['portfolio']['label']} (file: {p['portfolio']['file']})",
             f"- Cover letter: {p['cover_letter']['requirement']} — {p['cover_letter']['why']}", "",
             "## Skills", f"- Lead with: {', '.join(p['key_skills']['lead_with']) or '—'}",
             f"- Transferable: {', '.join(p['key_skills']['transferable']) or '—'}",
             f"- Do not claim: {', '.join(p['key_skills']['do_not_claim']) or '—'}", "", "## Project examples"]
    examples = p["portfolio"]["project_examples"]
    lines += ([f"- {e['project']}: {e['why']}" for e in examples] if isinstance(examples, list)
              else [f"- {examples}"])
    lines += ["", "## Networking (drafts only — you send them yourself)"]
    lines += [f"- [{a['priority']}] {a['contact_type']}: {a['reason']}. Angle: {a['outreach_angle']}"
              for a in p["networking_action"]] or ["- none suggested"]
    lines += ["", f"_Nothing in this packet has been sent or submitted. Model version {p['model_version']}._"]
    return "\n".join(lines)


def write_packet(job_id, out_dir=None):
    packet = build_packet(job_id)
    out_dir = Path(out_dir) if out_dir else paths.REPORTS_DIR / "packets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{packet['job']['id']}.md"
    out.write_text(packet_markdown(packet), encoding="utf-8")
    return out, packet
