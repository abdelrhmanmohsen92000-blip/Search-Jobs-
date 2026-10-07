"""Networking engine (V1.4).

For high-value opportunities, suggests WHO to reach (by contact TYPE, or a
known contact from tracking/networking.csv), WHY, with WHAT ANGLE, and
prepares a short outreach DRAFT.

    tracking/networking_actions.csv   one row per suggested action (stable action_id)

Hard rules:
    - nothing is ever sent: no email, no LinkedIn message, no connection
      request, no contact with a recruiter. `sent_by_system` is always False.
    - actions stay SUGGESTED until YOU change them (approve / done / dismiss)
    - drafts use only facts already in the system: the job title, the company
      name, skills from your profile that the posting asks for, your stated
      years of experience, and your own portfolio project names. No invented
      company facts, no invented names.
"""
import datetime as _dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

CONFIG_PATH = paths.CONFIG_DIR / "networking.yaml"
STATUSES = ("SUGGESTED", "APPROVED", "DONE", "REPLIED", "NO_RESPONSE", "DISMISSED")
OPEN_STATUSES = ("SUGGESTED", "APPROVED")
FIELDNAMES = [
    "action_id", "job_id", "company", "company_id", "target_role", "contact_type", "known_contact",
    "contact_profile_url", "priority", "reason", "outreach_angle", "draft_message", "status",
    "requires_human_approval", "sent_by_system", "created_at", "updated_at", "done_at", "follow_up_date", "notes",
]
_PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def is_eligible(analysis, config=None):
    config = config or load_config()
    rules = config.get("eligibility") or {}
    if analysis.get("decision") in (rules.get("decisions") or []):
        return True
    return (analysis.get("decision") == "REVIEW"
            and (analysis.get("opportunity_score") or 0) >= rules.get("min_opportunity_score", 101))


def contact_types_for(job, analysis, config=None):
    config = config or load_config()
    title = (job.get("job_title") or "").lower()
    contacts = None
    for family in config.get("role_family_contacts") or []:
        if any(k in title for k in family.get("keywords") or []):
            contacts = list(family.get("contacts") or [])
            break
    contacts = contacts or list(config.get("default_contacts") or ["hiring manager", "recruiter"])
    if analysis.get("decision") == "NETWORK_FIRST" and config.get("network_first_extra"):
        extra = config["network_first_extra"]
        contacts = [extra] + [c for c in contacts if c != extra]
    modes = {m.upper() for m in (job.get("matched_modes") or [])}
    etype = (job.get("employment_type") or "").lower()
    if (modes & {"FREELANCE", "CONTRACT", "PROJECT_BASED"} or any(w in etype for w in ("freelance", "contract", "project"))) \
            and config.get("project_based_extra") and config["project_based_extra"] not in contacts:
        contacts.insert(0, config["project_based_extra"])
    known = set(config.get("contact_types") or [])
    return [c for c in contacts if not known or c in known][: int(config.get("max_actions_per_job", 3))]


def _known_contact(company, contact_type, contacts):
    company_l = (company or "").strip().lower()
    words = [w for w in contact_type.lower().replace("/", " ").split() if len(w) > 3]
    for c in contacts or []:
        if (c.get("company") or "").strip().lower() != company_l:
            continue
        role = (c.get("role") or "").lower()
        if not words or any(w in role for w in words):
            return c
    return None


def _priority(analysis, index):
    decision = analysis.get("decision")
    if decision == "APPLY_NOW" or (decision == "NETWORK_FIRST" and index == 0):
        return "HIGH" if index == 0 else "MEDIUM"
    if decision in ("APPLY", "NETWORK_FIRST"):
        return "MEDIUM" if index == 0 else "LOW"
    return "LOW"


def _reason(job, analysis, contact_type, company):
    parts = []
    decision = analysis.get("decision")
    if decision == "NETWORK_FIRST":
        parts.append("Decision is NETWORK_FIRST — a warm contact can address the gaps before you apply")
    elif decision == "APPLY_NOW":
        parts.append("High-priority role — a contact in parallel with the application raises visibility")
    else:
        parts.append(f"{decision} opportunity (score {analysis.get('opportunity_score')})")
    if company and company.get("grade") in ("A+", "A"):
        parts.append(f"company grade {company['grade']} ({company.get('grade_label')})")
    gaps = (analysis.get("skills_gap") or {}).get("missing") or []
    if gaps and contact_type in ("hiring manager", "BIM manager", "department lead", "architecture director"):
        parts.append("can clarify how strict the gap(s) are: " + ", ".join(gaps[:3]))
    if contact_type == "recruiter":
        parts.append("recruiters route applications and can confirm the process and deadline")
    if contact_type == "employee/referral":
        parts.append("a referral is the strongest route in when you only partly match" if gaps or decision == "NETWORK_FIRST"
                     else "a referral puts your application in front of the team directly")
    return "; ".join(parts)


def _angle(job, analysis, profile):
    gap = analysis.get("skills_gap") or {}
    matched = gap.get("matched") or []
    years = profile.get("experience_years")
    angle = []
    if matched:
        angle.append("Lead with " + ", ".join(matched[:3]) + " — required in the posting and in your profile")
    if years:
        angle.append(f"{years} years of experience")
    portfolio = [r for r in analysis.get("reasons") or [] if r.startswith("Direct portfolio evidence")]
    if portfolio:
        angle.append(portfolio[0].replace("Direct portfolio evidence: ", "reference your project(s) "))
    location = (analysis.get("requirements") or {}).get("location")
    if location and location != "UNKNOWN":
        angle.append(f"show you are ready for {location}")
    return "; ".join(angle) or "Reference the exact job title and one concrete project of yours"


def _draft(job, analysis, contact_type, known, profile):
    """Short connection-note style draft. Uses only stored facts."""
    gap = analysis.get("skills_gap") or {}
    matched = gap.get("matched") or []
    first = (known or {}).get("person") or (known or {}).get("name") or ""
    greeting = f"Hi {first.split()[0]}," if first else "Hi,"
    years = profile.get("experience_years")
    skills = ", ".join(matched[:3]) if matched else "BIM and architectural design"
    who = f"{years} years in " if years else ""
    text = (f"{greeting} I saw the {job.get('job_title')} role at {job.get('company')}. "
            f"I'm an architect with {who}{skills}. ")
    if contact_type == "recruiter":
        text += "Could you tell me who is handling this role, or the best way to apply? Thank you."
    elif contact_type == "employee/referral":
        text += "Would you be open to a short chat about the team, and whether a referral makes sense? Thank you."
    else:
        text += "I'd value a few minutes to understand what the team needs most for this role. Thank you."
    return text


def recommend_actions(job, analysis, company=None, contacts=None, profile=None, config=None):
    """Suggested actions for one job (list of row dicts, not saved). Empty when the
    job is not high-value enough."""
    config = config or load_config()
    if not is_eligible(analysis, config):
        return []
    profile = cfg_lib.load_profile_skills() if profile is None else profile
    contacts = storage.read_csv(paths.NETWORKING_CSV) if contacts is None else contacts
    now = _now()
    actions = []
    for i, ctype in enumerate(contact_types_for(job, analysis, config)):
        known = _known_contact(job.get("company"), ctype, contacts)
        actions.append({
            "action_id": f"{job.get('id')}:{_slug(ctype)}", "job_id": job.get("id"),
            "company": job.get("company"), "company_id": (company or {}).get("company_id") or _slug(job.get("company")),
            "target_role": job.get("job_title"), "contact_type": ctype,
            "known_contact": (known or {}).get("person") or (known or {}).get("name") or "",
            "contact_profile_url": (known or {}).get("profile_url") or (known or {}).get("linkedin_url") or "",
            "priority": _priority(analysis, i), "reason": _reason(job, analysis, ctype, company),
            "outreach_angle": _angle(job, analysis, profile), "draft_message": _draft(job, analysis, ctype, known, profile),
            "status": "SUGGESTED", "requires_human_approval": True, "sent_by_system": False,
            "created_at": now, "updated_at": now, "done_at": "", "follow_up_date": "", "notes": "",
        })
    return actions


def load_actions(csv_path=None):
    return storage.read_csv(csv_path or paths.NETWORKING_ACTIONS_CSV)


def save_suggestions(actions, csv_path=None):
    """Upserts suggestions by action_id. An action you already touched (any
    status other than SUGGESTED) keeps its status, dates and notes — only the
    suggestion text is refreshed. Returns (inserted, refreshed)."""
    csv_path = csv_path or paths.NETWORKING_ACTIONS_CSV
    rows = load_actions(csv_path)
    index = {r["action_id"]: i for i, r in enumerate(rows)}
    inserted = refreshed = 0
    for a in actions:
        i = index.get(a["action_id"])
        if i is None:
            index[a["action_id"]] = len(rows)
            rows.append(a)
            inserted += 1
        else:
            keep = {k: rows[i].get(k) for k in ("status", "created_at", "done_at", "follow_up_date", "notes")}
            rows[i] = {**a, **keep, "updated_at": rows[i].get("updated_at") or a["updated_at"]}
            refreshed += 1
    storage.write_csv(csv_path, FIELDNAMES, rows)
    return inserted, refreshed


def update_status(action_id, status, note="", csv_path=None, today=None):
    """Your manual update of one action. DONE means YOU sent it yourself; the
    system schedules a follow-up reminder from that date."""
    status = status.upper()
    if status not in STATUSES:
        raise ValueError(f"Unknown networking status {status!r}; use one of {', '.join(STATUSES)}")
    csv_path = csv_path or paths.NETWORKING_ACTIONS_CSV
    rows = load_actions(csv_path)
    row = next((r for r in rows if r["action_id"] == action_id or r["action_id"].startswith(action_id)), None)
    if row is None:
        raise KeyError(f"No networking action {action_id!r}")
    today = today or _dt.date.today()
    row["status"] = status
    row["updated_at"] = _now()
    if status == "DONE":
        row["done_at"] = today.isoformat()
        days = int(load_config().get("follow_up_days", 7))
        row["follow_up_date"] = (today + _dt.timedelta(days=days)).isoformat()
    if note:
        row["notes"] = (row.get("notes") + " | " if row.get("notes") else "") + note
    storage.write_csv(csv_path, FIELDNAMES, rows)
    return row


def open_actions(rows=None):
    rows = load_actions() if rows is None else rows
    return sorted([r for r in rows if r.get("status") in OPEN_STATUSES],
                  key=lambda r: (_PRIORITY_ORDER.get(r.get("priority"), 9), r.get("company") or ""))


def due_followups(rows=None, today=None):
    rows = load_actions() if rows is None else rows
    today = (today or _dt.date.today()).isoformat()
    return [r for r in rows if r.get("status") == "DONE" and r.get("follow_up_date") and r["follow_up_date"] <= today]


def refresh_from_jobs(jobs=None, csv_path=None):
    """Builds suggestions for every eligible job in tracking/jobs.csv."""
    from scripts.intelligence import career_data, company_intel
    jobs = career_data.load_jobs() if jobs is None else jobs
    index = company_intel.build_company_index()
    lookup = company_intel.make_lookup(index)
    contacts = storage.read_csv(paths.NETWORKING_CSV)
    profile = cfg_lib.load_profile_skills()
    config = load_config()
    actions = []
    for row in jobs:
        analysis = career_data.analysis_for(row, company_lookup=lookup, contacts=contacts)
        job = career_data.to_opportunity(row)
        actions += recommend_actions(job, analysis, lookup(row.get("company")), contacts, profile, config)
    inserted, refreshed = save_suggestions(actions, csv_path)
    return {"suggested": len(actions), "inserted": inserted, "refreshed": refreshed}
