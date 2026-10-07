"""Company intelligence (V1.4).

Builds one record per company from what this system has actually observed:

    tracking/jobs.csv               job count, active opportunities, hiring trend, average match
    config/target_companies.yaml    target status, priority, regions, careers page
    tracking/companies.csv          industry, size, website (when a human logged them)
    tracking/networking.csv         known contacts
    tracking/applications.csv       previous applications
    config/company_overrides.yaml   manual grade overrides (always win)

and scores it 0-100 into grades A+ TARGET / A HIGH PRIORITY / B GOOD /
C NORMAL / D LOW PRIORITY. Anything not observed stays UNKNOWN — no company
fact (size, industry, reputation) is ever invented.
"""
import collections
import datetime as _dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

UNKNOWN = "UNKNOWN"
OVERRIDES_PATH = paths.CONFIG_DIR / "company_overrides.yaml"
GRADES = (("A+", 85, "TARGET"), ("A", 72, "HIGH PRIORITY"), ("B", 58, "GOOD"), ("C", 45, "NORMAL"), ("D", 0, "LOW PRIORITY"))
GRADE_LABELS = {g: label for g, _, label in GRADES}
_PRIORITY_POINTS = {"HIGH": 25, "MEDIUM": 15, "LOW": 8}
_INACTIVE = ("CLOSED", "STALE")


def company_id(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "unknown"


def grade_for(score):
    for grade, threshold, _ in GRADES:
        if score >= threshold:
            return grade
    return "D"


def load_overrides(path=None):
    path = Path(path) if path else OVERRIDES_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k.strip().lower(): v or {} for k, v in (data.get("companies") or {}).items()}


def _region_tier_for(countries, regions, matrix):
    tiers = matrix.get("target_locations") or []
    best = None
    for t in tiers:
        names = {x.lower() for x in t.get("locations") or []}
        if (t.get("region") in (regions or [])) or any(c.lower() in names for c in countries if c):
            best = t if best is None or t.get("tier", 99) < best.get("tier", 99) else best
    return best


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trend(dates, today):
    recent = sum(1 for d in dates if d and (today - d).days <= 30)
    previous = sum(1 for d in dates if d and 30 < (today - d).days <= 60)
    if recent + previous < 2:
        return "INSUFFICIENT_DATA"
    if recent > previous:
        return "GROWING"
    if recent < previous:
        return "DECLINING"
    return "STABLE"


def build_company_index(jobs=None, targets=None, companies=None, contacts=None, applications=None, overrides=None,
                        extra_jobs=None, matrix=None, today=None):
    """{company_id: record}. Every argument defaults to the live trackers/config."""
    from scripts.sources import company_careers
    jobs = storage.read_csv(paths.JOBS_CSV) if jobs is None else jobs
    jobs = list(jobs) + list(extra_jobs or [])
    targets = company_careers.load_targets() if targets is None else targets
    companies = storage.read_csv(paths.COMPANIES_CSV) if companies is None else companies
    contacts = storage.read_csv(paths.NETWORKING_CSV) if contacts is None else contacts
    applications = storage.read_csv(paths.APPLICATIONS_CSV) if applications is None else applications
    overrides = load_overrides() if overrides is None else overrides
    matrix = cfg_lib.load_search_matrix() if matrix is None else matrix
    today = today or _dt.date.today()

    index = {}

    def rec(name):
        cid = company_id(name)
        if cid not in index:
            index[cid] = {"company_id": cid, "company": name, "industry": UNKNOWN, "size": UNKNOWN, "website": UNKNOWN,
                          "careers_page": UNKNOWN, "regions": [], "countries": [], "is_target": False,
                          "target_priority": None, "jobs": [], "contacts": [], "applications": [], "notes": ""}
        return index[cid]

    for t in targets:
        r = rec(t.get("company"))
        r.update(is_target=True, target_priority=(t.get("priority") or "MEDIUM").upper(),
                 regions=list(t.get("regions") or []), industry=t.get("source_type") or UNKNOWN)
        if (t.get("career_url") or UNKNOWN) != UNKNOWN:
            r["careers_page"] = t["career_url"]
    for c in companies:
        if not c.get("company_name"):
            continue
        r = rec(c["company_name"])
        for src, dst in (("industry", "industry"), ("company_size", "size"), ("website", "website"),
                         ("careers_page", "careers_page")):
            if c.get(src) and r[dst] == UNKNOWN:
                r[dst] = c[src]
        if c.get("country"):
            r["countries"].append(c["country"])
    for j in jobs:
        if j.get("company"):
            r = rec(j["company"])
            r["jobs"].append(j)
            if j.get("country"):
                r["countries"].append(j["country"])
            if j.get("company_career_url") and r["careers_page"] == UNKNOWN:
                r["careers_page"] = j["company_career_url"]
    for c in contacts:
        if c.get("company"):
            rec(c["company"])["contacts"].append(c.get("person") or c.get("name") or "")
    for a in applications:
        if a.get("company"):
            rec(a["company"])["applications"].append({"job_title": a.get("job_title"), "status": a.get("status")})

    for r in index.values():
        jobs_r = r.pop("jobs")
        r["countries"] = sorted({c for c in r["countries"] if c})
        r["job_count"] = len(jobs_r)
        active = [j for j in jobs_r if (j.get("lifecycle_status") or j.get("freshness") or "") not in _INACTIVE
                  and (j.get("freshness") or "") != "CLOSED"]
        r["active_opportunities"] = len(active)
        dates = []
        for j in jobs_r:
            try:
                dates.append(_dt.date.fromisoformat(str(j.get("date_found") or "")[:10]))
            except ValueError:
                pass
        r["hiring_trend"] = _trend(dates, today)
        scores = [s for s in (_float(j.get("score") if "score" in j else j.get("match_score")) for j in jobs_r) if s is not None]
        r["average_match"] = round(sum(scores) / len(scores), 1) if scores else None

        tier = _region_tier_for(r["countries"], r["regions"], matrix)
        r["region_tier"] = tier.get("tier") if tier else None
        score = 40.0
        score += _PRIORITY_POINTS.get(r["target_priority"] or "", 0)
        score += (6 - tier["tier"]) * 3 if tier else 0
        score += min(15, 5 * r["active_opportunities"])
        if r["average_match"] is not None:
            score += max(-10, min(10, (r["average_match"] - 50) * 0.4))
        score += {"GROWING": 5, "DECLINING": -5}.get(r["hiring_trend"], 0)
        score += 5 if r["contacts"] else 0
        r["company_score"] = round(max(0, min(100, score)), 1)
        r["computed_grade"] = grade_for(r["company_score"])
        override = overrides.get((r["company"] or "").strip().lower()) or {}
        r["grade"] = override.get("grade") or r["computed_grade"]
        r["grade_label"] = GRADE_LABELS.get(r["grade"], "NORMAL")
        r["manual_override"] = bool(override.get("grade"))
        r["notes"] = override.get("notes") or ""
        r["networking_opportunities"] = len(r["contacts"])
    return index


def make_lookup(index):
    def lookup(name):
        return index.get(company_id(name))
    return lookup


def ranked(index):
    order = {g: i for i, (g, _, _) in enumerate(GRADES)}
    return sorted(index.values(), key=lambda r: (order.get(r["grade"], 9), -r["company_score"], r["company"] or ""))
