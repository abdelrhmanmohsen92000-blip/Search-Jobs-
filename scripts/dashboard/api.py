"""Dashboard JSON API (V1.6) — a pure function of (method, path, query, body).

Kept free of sockets so every endpoint is unit-testable; scripts/dashboard/server.py
only adapts HTTP to `handle()`.

    GET  /api/overview | jobs | jobs/<id> | opportunities | companies | companies/<id>
         applications | networking | interviews | skills | market | sources | settings | notifications
    POST /api/applications/<job_id>/move     {"status", "note"}      (Kanban; actor human:dashboard)
    POST /api/networking/<action_id>/status  {"status", "note"}      (your manual update — nothing is sent)
    POST /api/feedback                       {"kind", "job_id", "reason", "rating"}
    POST /api/notifications/read             {"notification_id"?}

Every write is an explicit action by the person using the dashboard. No endpoint
applies to a job, sends a message, contacts anyone, or changes model weights
(learning suggestions are approved on the CLI).
"""
import collections
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, runtime, storage  # noqa: E402

_cache = {"key": None, "views": None}


def _signature():
    files = [paths.JOBS_CSV, paths.APPLICATIONS_CSV, paths.ANALYSES_CSV, paths.NETWORKING_CSV,
             paths.CONFIG_DIR / "scoring_model.yaml", paths.WORKSPACE / "config" / "scoring_model.yaml",
             paths.CONFIG_DIR / "company_overrides.yaml"]
    return (str(paths.WORKSPACE),) + tuple((str(f), f.stat().st_mtime_ns if f.exists() else 0) for f in files)


def views():
    from scripts.intelligence import insights
    key = _signature()
    if _cache["key"] != key:
        _cache["views"], _cache["key"] = insights.job_views(), key
    return _cache["views"]


def invalidate():
    _cache["key"] = None


def _q(query, name):
    value = (query or {}).get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    return value if value not in ("", None) else None


# --- GET handlers ---------------------------------------------------------------------

def overview(query):
    from scripts.intelligence import application_pipeline as ap, briefs, insights, networking_engine, notifications
    v = views()
    active = [x for x in v if insights.is_active(x)]
    brief = briefs.daily_brief(views=v)
    notes = notifications.load_notifications()
    unread = [n for n in notes if str(n.get("read")) != "True"]
    counts = collections.Counter(x["decision"] for x in v)
    in_progress = [x for x in v if x["status"] in ("SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER")]
    return {
        "workspace": str(paths.WORKSPACE), "is_default_workspace": paths.WORKSPACE == paths.ROOT,
        "network_mode": runtime.network_mode(), "synthetic_jobs": sum(1 for x in v if x["synthetic"]),
        "tiles": {"jobs": len(v), "active": len(active), "apply_now": len(brief["apply_now"]),
                  "in_pipeline": len(in_progress), "interviews": len(ap.upcoming_interviews()),
                  "followups_due": len(brief["application_followups"]) + len(brief["networking_followups"]),
                  "open_networking": len(networking_engine.open_actions()), "unread_notifications": len(unread)},
        "decisions": [{"decision": d, "count": counts.get(d, 0)} for d in
                      ("APPLY_NOW", "APPLY", "NETWORK_FIRST", "REVIEW", "WATCH", "SKIP")],
        "top_opportunities": brief["top_opportunities"][:8], "apply_now": brief["apply_now"],
        "network_first": brief["network_first"], "followups": brief["application_followups"],
        "interviews": brief["interviews"], "market_signals": brief["market_signals"],
        "skills_gaps": brief["skills_gaps"], "notifications": list(reversed(unread))[:10],
    }


def jobs(query):
    from scripts.intelligence import insights
    v = views()
    filtered = insights.filter_jobs(
        v, country=_q(query, "country"), city=_q(query, "city"), role=_q(query, "role"), company=_q(query, "company"),
        min_score=_q(query, "min_score"), employment_type=_q(query, "employment_type"), remote=_q(query, "remote"),
        freshness=_q(query, "freshness"), status=_q(query, "status"), decision=_q(query, "decision"), q=_q(query, "q"),
        sort=_q(query, "sort") or "opportunity_score", desc=(_q(query, "order") or "desc") != "asc")

    def facet(key):
        return sorted({str(x[key]) for x in v if x[key] not in (None, "")})
    return {"total": len(v), "count": len(filtered), "jobs": filtered,
            "facets": {k: facet(k) for k in ("country", "city", "role_family", "company", "employment_type",
                                              "freshness", "status", "decision")}}


def job_detail(job_id):
    from scripts.intelligence import application_pipeline as ap, career_data, feedback, networking_engine
    row = career_data.find_job(job_id)
    if row is None:
        return 404, {"error": f"No job {job_id}"}
    view = next((x for x in views() if x["id"] == row["id"]), None)
    analysis = career_data.analysis_for(row)
    return 200, {
        "job": view, "description": row.get("description") or "", "analysis": analysis,
        "packet": ap.build_packet(row["id"]), "history": ap.history(row["id"]),
        "application": ap.get_application(row["id"]),
        "networking": [a for a in networking_engine.load_actions() if a.get("job_id") == row["id"]],
        "feedback": [f for f in feedback.load_feedback() if f.get("job_id") == row["id"]],
        "allowed_statuses": list(ap.STATUSES), "feedback_kinds": list(feedback.KINDS),
        "provenance": {"source": row.get("source"), "source_url": row.get("source_url"),
                       "retrieved_at": row.get("retrieved_at"), "extraction_method": row.get("extraction_method"),
                       "field_sources": (analysis.get("requirements") or {}).get("field_sources") or {}},
    }


def opportunities(query):
    groups = collections.OrderedDict((d, []) for d in ("APPLY_NOW", "APPLY", "NETWORK_FIRST", "REVIEW"))
    from scripts.intelligence import insights
    for x in sorted(views(), key=lambda x: -(x["opportunity_score"] or 0)):
        if x["decision"] in groups and insights.is_active(x):
            groups[x["decision"]].append(x)
    return {"groups": [{"decision": d, "jobs": j} for d, j in groups.items()]}


def companies(query):
    from scripts.intelligence import company_intel
    index = company_intel.build_company_index()
    rows = [{k: c[k] for k in ("company_id", "company", "grade", "grade_label", "company_score", "computed_grade",
                               "manual_override", "job_count", "active_opportunities", "hiring_trend",
                               "average_match", "region_tier", "is_target", "target_priority", "countries",
                               "industry", "size", "website", "careers_page", "networking_opportunities", "notes")}
            for c in company_intel.ranked(index)]
    return {"companies": rows, "grades": [{"grade": g, "label": label} for g, _, label in company_intel.GRADES]}


def company_detail(company_id):
    from scripts.intelligence import company_intel, networking_engine
    index = company_intel.build_company_index()
    rec = index.get(company_id)
    if rec is None:
        return 404, {"error": f"No company {company_id}"}
    return 200, {"company": rec, "jobs": [x for x in views() if x["company_id"] == company_id],
                 "networking": [a for a in networking_engine.load_actions() if a.get("company_id") == company_id]}


def applications(query):
    from scripts.intelligence import application_pipeline as ap
    board = ap.board()
    closed = board.pop("_closed")
    cols = ap.load_config().get("kanban_columns") or list(board)
    events = storage.read_csv(paths.APPLICATION_EVENTS_CSV)
    return {"columns": cols, "board": board, "closed": closed, "funnel": ap.funnel(),
            "recent_events": list(reversed(events))[:20], "statuses": list(ap.STATUSES)}


def networking(query):
    from scripts.intelligence import networking_engine
    actions = networking_engine.load_actions()
    return {"open": networking_engine.open_actions(actions), "followups_due": networking_engine.due_followups(actions),
            "by_status": dict(collections.Counter(a.get("status") for a in actions)),
            "done": [a for a in actions if a.get("status") in ("DONE", "REPLIED", "NO_RESPONSE")],
            "statuses": list(networking_engine.STATUSES),
            "policy": "Drafts only. Career Hunter never sends messages or connection requests — you do."}


def interviews(query):
    from scripts.intelligence import application_pipeline as ap
    f = ap.funnel()
    return {"upcoming": ap.upcoming_interviews(),
            "funnel": [{"stage": s, "count": f.get(s, 0)} for s in ("APPLIED", "INTERVIEW", "OFFER")],
            "offers": [a for a in ap.load_applications() if ap.normalize_status(a.get("status")) == "OFFER"]}


def skills(query):
    from scripts.intelligence import insights
    return insights.skills_intelligence(views())


def market(query):
    from scripts.intelligence import insights
    return insights.market_intelligence(views())


def sources(query):
    from scripts import research
    from scripts.intelligence import insights
    from scripts.lib import source_registry
    runs = sorted(research.load_research_runs(), key=lambda r: r.get("started_at") or "")[-10:]
    return {"health": insights.source_summary(),
            "registry": [{k: s.get(k) for k in ("name", "implementation", "enabled", "credential_env",
                                                "credential_present")} for s in source_registry.list_sources()],
            "runs": [{k: r.get(k) for k in ("run_id", "started_at", "status", "network_mode", "requests",
                                            "raw_results", "new_opportunities", "updated_opportunities",
                                            "sources_blocked")} for r in reversed(runs)]}


def settings(query):
    from scripts import scheduler
    from scripts.intelligence import learning_loop, notifications, opportunity_priority, scoring_model
    data = scoring_model.load_all()
    versions = [{"version": v, "active": v == str(data.get("active_version")), "created_at": m.get("created_at"),
                 "created_by": m.get("created_by"), "notes": m.get("notes")} for v, m in (data.get("versions") or {}).items()]
    learning = learning_loop.evaluate(save=False)
    return {
        "workspace": str(paths.WORKSPACE), "network_mode": runtime.network_mode(),
        "environment": runtime.environment_status(), "environment_help": runtime.ENVIRONMENT_VARIABLES,
        "timezone": scheduler.timezone_name(), "schedules": scheduler.status(),
        "model": {"active_version": str(data.get("active_version")), "path": str(scoring_model.default_path()),
                  "versions": versions},
        "learning": {k: learning.get(k) for k in ("status", "message", "outcomes", "min_outcomes", "by_outcome",
                                                   "top_rejection_reasons")},
        "suggestions": learning_loop.load_suggestions(),
        "notifications": notifications.load_config().get("channels"),
        "career_goal": opportunity_priority.load_settings().get("goal"),
        "human_approval": ["Applying to any job", "Sending any email, LinkedIn message or connection request",
                           "Contacting any recruiter or employee", "Approving a learning suggestion (new model version)",
                           "Activating a model version"],
    }


def notifications_list(query):
    from scripts.intelligence import notifications
    return {"notifications": list(reversed(notifications.load_notifications()))[:100]}


GET_ROUTES = {"overview": overview, "jobs": jobs, "opportunities": opportunities, "companies": companies,
              "applications": applications, "networking": networking, "interviews": interviews, "skills": skills,
              "market": market, "sources": sources, "settings": settings, "notifications": notifications_list}


# --- POST handlers --------------------------------------------------------------------

def move_application(job_id, body):
    from scripts.intelligence import application_pipeline as ap
    status = (body or {}).get("status")
    if not status:
        return 400, {"error": "status is required"}
    try:
        rec = ap.transition(job_id, status, actor="human:dashboard", note=(body or {}).get("note") or "",
                            force=bool((body or {}).get("force")))
    except KeyError as exc:
        return 404, {"error": str(exc).strip("'\"")}
    except ValueError as exc:
        return 409, {"error": str(exc)}
    invalidate()
    return 200, {"application": rec, "history": ap.history(rec["opportunity_id"])}


def networking_status(action_id, body):
    from scripts.intelligence import networking_engine
    try:
        row = networking_engine.update_status(action_id, (body or {}).get("status") or "", note=(body or {}).get("note") or "")
    except KeyError as exc:
        return 404, {"error": str(exc).strip("'\"")}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, {"action": row}


def post_feedback(body):
    from scripts.intelligence import feedback
    body = body or {}
    try:
        row, rec = feedback.record(body.get("kind"), body.get("job_id"), reason=body.get("reason") or "",
                                   rating=body.get("rating"), note=body.get("note") or "", actor="human:dashboard")
    except KeyError as exc:
        return 404, {"error": str(exc).strip("'\"")}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    invalidate()
    return 200, {"feedback": row, "application": rec}


def mark_read(body):
    from scripts.intelligence import notifications
    return 200, {"marked": notifications.mark_read((body or {}).get("notification_id"))}


# --- dispatcher -----------------------------------------------------------------------

def handle(method, path, query=None, body=None):
    """Returns (http_status, json_payload)."""
    parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/") if p]
    if len(parts) < 2 or parts[0] != "api":
        return 404, {"error": "Not found"}
    route = parts[1:]
    try:
        if method == "GET":
            if len(route) == 1 and route[0] in GET_ROUTES:
                return 200, GET_ROUTES[route[0]](query or {})
            if len(route) == 2 and route[0] == "jobs":
                return job_detail(route[1])
            if len(route) == 2 and route[0] == "companies":
                return company_detail(route[1])
        elif method == "POST":
            if len(route) == 3 and route[0] == "applications" and route[2] == "move":
                return move_application(route[1], body)
            if len(route) == 3 and route[0] == "networking" and route[2] == "status":
                return networking_status(route[1], body)
            if route == ["feedback"]:
                return post_feedback(body)
            if route == ["notifications", "read"]:
                return mark_read(body)
        else:
            return 405, {"error": "Method not allowed"}
    except Exception as exc:  # the dashboard reports the error instead of crashing the server
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return 404, {"error": "Not found"}
