"""Read-only intelligence views over the stored data (V1.5 / V1.6).

Used by the CLI (`jobs`, `skills`, `market`), the daily/weekly reports and
the dashboard API, so every surface shows the same numbers:

    job_views()           one flat record per job: row + analysis + pipeline status
    skills_intelligence() skill demand, gaps and a learning priority list
    market_intelligence() jobs by country / role / company / type, trends, salaries
    source_summary()      source health grouped by state

Everything is computed from tracking/*.csv and data/analyses/*.json only. A
salary statistic uses posted salaries only; nothing is estimated.
"""
import collections
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

UNKNOWN = "UNKNOWN"
INACTIVE_FRESHNESS = ("CLOSED", "STALE")
_FALLBACK_FAMILIES = (("facade", "Exterior Designer"), ("exterior", "Exterior Designer"), ("landscape", "Landscape Designer"),
                      ("interior", "Interior Designer"), ("revit", "Revit Specialist"), ("bim", "BIM Specialist"),
                      ("architect", "Architect"), ("designer", "Architectural Designer"))


def role_family(title, matrix=None):
    matrix = matrix if matrix is not None else cfg_lib.load_search_matrix()
    t = (title or "").lower()
    roles = [r for tier in (matrix.get("role_query_matrix") or {}).values() for r in tier or []]
    hits = sorted((r for r in roles if r.lower() in t), key=len, reverse=True)
    if hits:
        return hits[0]
    return next((family for word, family in _FALLBACK_FAMILIES if word in t), "Other")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_synthetic(row):
    return (row.get("source") == "SYNTHETIC_DEMO" or (row.get("company") or "").startswith("[SYNTHETIC]")
            or "synthetic.example" in (row.get("source_url") or ""))


def job_views(jobs=None, applications=None):
    from scripts.intelligence import application_pipeline as ap, career_data, company_intel
    jobs = career_data.load_jobs() if jobs is None else jobs
    applications = ap.load_applications() if applications is None else applications
    apps = {a.get("opportunity_id"): a for a in applications}
    index = company_intel.build_company_index(jobs=jobs, applications=applications)
    lookup = company_intel.make_lookup(index)
    contacts = storage.read_csv(paths.NETWORKING_CSV)
    matrix = cfg_lib.load_search_matrix()
    views = []
    for row in jobs:
        a = career_data.analysis_for(row, company_lookup=lookup, contacts=contacts)
        gap = a.get("skills_gap") or {}
        req = a.get("requirements") or {}
        company = lookup(row.get("company")) or {}
        app = apps.get(row["id"])
        views.append({
            "id": row["id"], "job_title": row.get("job_title"), "company": row.get("company"),
            "company_id": company.get("company_id") or company_intel.company_id(row.get("company")),
            "company_grade": company.get("grade"), "country": row.get("country") or UNKNOWN,
            "city": row.get("city") or UNKNOWN, "region": row.get("region") or "",
            "remote": str(row.get("remote")) == "True" or req.get("work_mode") == "REMOTE",
            "work_mode": req.get("work_mode") or UNKNOWN,
            "employment_type": row.get("employment_type") or req.get("employment_type") or UNKNOWN,
            "role_family": role_family(row.get("job_title"), matrix), "source": row.get("source"),
            "date_found": row.get("date_found") or "", "date_posted": row.get("date_posted") or "",
            "closing_date": row.get("closing_date") or "", "freshness": a.get("freshness") or row.get("freshness") or UNKNOWN,
            "decision": a.get("decision"), "decision_icon": a.get("decision_icon"),
            "overall_match": a.get("overall_match"), "opportunity_score": a.get("opportunity_score"),
            "confidence": a.get("confidence"), "model_version": a.get("model_version"),
            "status": ap.effective_status(row, app), "application_url": row.get("application_url") or UNKNOWN,
            "job_page_url": row.get("job_page_url") or row.get("source_url") or UNKNOWN,
            "matched_skills": gap.get("matched") or [], "missing_skills": gap.get("missing") or [],
            "transferable_skills": [t["skill"] for t in gap.get("transferable") or []],
            "preferred_missing": gap.get("preferred_missing") or [], "required_skills": req.get("required_skills") or [],
            "preferred_skills": req.get("preferred_skills") or [], "salary": req.get("salary") or UNKNOWN,
            "synthetic": is_synthetic(row), "analysis_stored": a.get("stored", False),
        })
    return views


def is_active(view):
    from scripts.intelligence.application_pipeline import CLOSED_OUT
    return (view["freshness"] not in INACTIVE_FRESHNESS and view["decision"] != "SKIP"
            and view["status"] not in CLOSED_OUT)


def filter_jobs(views, country=None, city=None, role=None, company=None, min_score=None, employment_type=None,
                remote=None, freshness=None, status=None, decision=None, q=None, sort="opportunity_score", desc=True):
    def has(value, needle):
        return needle is None or needle == "" or needle.lower() in str(value or "").lower()
    out = [v for v in views
           if has(v["country"], country) and has(v["city"], city) and has(v["role_family"] + " " + (v["job_title"] or ""), role)
           and has(v["company"], company) and has(v["employment_type"], employment_type)
           and (freshness in (None, "") or v["freshness"] == freshness.upper())
           and (status in (None, "") or v["status"] == status.upper())
           and (decision in (None, "") or v["decision"] == decision.upper())
           and (remote in (None, "") or v["remote"] == (str(remote).lower() in ("1", "true", "yes")))
           and (min_score in (None, "") or (v["opportunity_score"] or 0) >= float(min_score))
           and (q in (None, "") or q.lower() in f"{v['job_title']} {v['company']} {v['city']} {v['country']}".lower())]
    key = sort if sort in ("opportunity_score", "overall_match", "confidence", "date_found", "date_posted", "company",
                           "job_title", "country") else "opportunity_score"
    numeric = key in ("opportunity_score", "overall_match", "confidence")
    out.sort(key=lambda v: (v[key] or 0) if numeric else str(v[key] or ""), reverse=desc)
    return out


# --- skills -----------------------------------------------------------------------------

def skills_intelligence(views=None, profile=None):
    from scripts.intelligence.requirements_extractor import candidate_skill_set, load_taxonomy
    views = job_views() if views is None else views
    profile = cfg_lib.load_profile_skills() if profile is None else profile
    taxonomy = load_taxonomy()
    have = candidate_skill_set(profile, taxonomy)
    active = [v for v in views if is_active(v)]
    demand = collections.defaultdict(lambda: {"required": 0, "preferred": 0, "jobs": [], "opportunity": []})
    for v in active:
        for s in v["required_skills"]:
            demand[s]["required"] += 1
            demand[s]["jobs"].append(v["id"])
            demand[s]["opportunity"].append(v["opportunity_score"] or 0)
        for s in v["preferred_skills"]:
            demand[s]["preferred"] += 1
            demand[s]["jobs"].append(v["id"])
            demand[s]["opportunity"].append(v["opportunity_score"] or 0)
    transferable = {s for v in active for s in v["transferable_skills"]}
    rows = []
    for skill, d in demand.items():
        status = "MATCHED" if skill in have else "TRANSFERABLE" if skill in transferable else "MISSING"
        avg_opp = round(sum(d["opportunity"]) / len(d["opportunity"]), 1) if d["opportunity"] else 0
        rows.append({"skill": skill, "category": (taxonomy["skills"].get(skill) or {}).get("category", UNKNOWN),
                     "required_in": d["required"], "preferred_in": d["preferred"], "jobs": len(set(d["jobs"])),
                     "avg_opportunity": avg_opp, "status": status,
                     "demand_score": round(d["required"] * 2 + d["preferred"], 1)})
    rows.sort(key=lambda r: (-r["demand_score"], r["skill"]))
    priority = [dict(r, priority_score=round(r["demand_score"] * (r["avg_opportunity"] / 100 + 0.5), 1),
                     unlocks=sorted({v["job_title"] for v in active if r["skill"] in v["missing_skills"]
                                     or r["skill"] in v["transferable_skills"] or r["skill"] in v["preferred_missing"]}))
                for r in rows if r["status"] != "MATCHED"]
    priority.sort(key=lambda r: -r["priority_score"])
    return {"active_jobs": len(active), "demand": rows, "matched": [r for r in rows if r["status"] == "MATCHED"],
            "missing": [r for r in rows if r["status"] == "MISSING"],
            "transferable": [r for r in rows if r["status"] == "TRANSFERABLE"], "priority_learning": priority[:10],
            "note": "Computed from requirements stated in active postings; skills you hold are read from "
                    "config/profile_skills.yaml."}


# --- market -----------------------------------------------------------------------------

def _week(date_text):
    try:
        y, w, _ = _dt.date.fromisoformat(str(date_text)[:10]).isocalendar()
        return f"{y}-W{w:02d}"
    except ValueError:
        return None


def market_intelligence(views=None, today=None):
    from scripts.intelligence import company_intel
    views = job_views() if views is None else views
    today = today or _dt.date.today()
    active = [v for v in views if is_active(v)]

    def count(key, rows=active, n=15):
        return collections.Counter(r[key] for r in rows if r[key] not in (None, "")).most_common(n)
    by_week = collections.Counter(w for w in (_week(v["date_found"]) for v in views) if w)
    this_week, last_week = _week(today.isoformat()), _week((today - _dt.timedelta(days=7)).isoformat())
    buckets = collections.Counter()
    for v in views:
        s = v["opportunity_score"]
        if s is not None:
            low = min(90, int(s // 10) * 10)
            buckets[f"{low}-{low + 9}" if low < 90 else "90-100"] += 1
    salaries = collections.defaultdict(list)
    for v in views:
        sal = v["salary"]
        if isinstance(sal, dict) and (sal.get("salary_max") or sal.get("salary_min")):
            salaries[f"{sal.get('salary_currency')}/{sal.get('salary_period')}"].append(
                float(sal.get("salary_max") or sal.get("salary_min")))
    companies = company_intel.ranked(company_intel.build_company_index())
    return {
        "total_jobs": len(views), "active_jobs": len(active),
        "by_country": count("country"), "by_city": count("city"), "by_role": count("role_family"),
        "by_company": count("company", n=10), "by_employment_type": count("employment_type"),
        "by_decision": collections.Counter(v["decision"] for v in views).most_common(),
        "remote_share": round(sum(1 for v in active if v["remote"]) / len(active) * 100, 1) if active else None,
        "opportunity_distribution": sorted(buckets.items()),
        "jobs_found_by_week": sorted(by_week.items())[-12:],
        "this_week_vs_last": {"this_week": by_week.get(this_week, 0), "last_week": by_week.get(last_week, 0)},
        "posted_salaries": {k: {"n": len(v), "min": min(v), "max": max(v), "median": sorted(v)[len(v) // 2]}
                            for k, v in salaries.items()},
        "salary_note": "Only salaries stated in postings; UNKNOWN salaries are excluded, never estimated.",
        "top_companies": [{"company": c["company"], "company_id": c["company_id"], "grade": c["grade"],
                           "active_opportunities": c["active_opportunities"], "hiring_trend": c["hiring_trend"]}
                          for c in companies if c["job_count"]][:10],
        "signals": _signals(active, by_week, this_week, last_week),
    }


def _signals(active, by_week, this_week, last_week):
    signals = []
    tw, lw = by_week.get(this_week, 0), by_week.get(last_week, 0)
    if tw or lw:
        trend = "up" if tw > lw else "down" if tw < lw else "flat"
        signals.append(f"New jobs found this week: {tw} (last week {lw}) — {trend}")
    for country, n in collections.Counter(v["country"] for v in active).most_common(2):
        if n >= 2 and country != UNKNOWN:
            signals.append(f"{country}: {n} active opportunities")
    for role, n in collections.Counter(v["role_family"] for v in active).most_common(2):
        if n >= 2:
            signals.append(f"Most demanded role: {role} ({n} active)")
    if not signals:
        signals.append("Not enough data yet for market signals (sample too small)")
    return signals


# --- sources --------------------------------------------------------------------------

def source_summary():
    from scripts.lib import source_health
    rows = source_health.load_health()
    states = collections.Counter((r.get("health_state") or "UNKNOWN") for r in rows.values())
    failing = [{"source": n, "health_state": r.get("health_state"), "error_type": r.get("error_type"),
                "consecutive_failures": r.get("consecutive_failures"), "cooldown_until": r.get("cooldown_until")}
               for n, r in rows.items() if (r.get("health_state") or "") in ("BLOCKED", "UNAVAILABLE", "PARSER_FAILED",
                                                                            "RATE_LIMITED", "AUTH_REQUIRED")]
    return {"sources": len(rows), "by_state": dict(states), "failing": failing,
            "rows": [{"source": n, **{k: r.get(k) for k in ("health_state", "status", "last_attempt", "last_success",
                                                             "consecutive_failures", "error_type", "cooldown_until")}}
                     for n, r in sorted(rows.items())]}
