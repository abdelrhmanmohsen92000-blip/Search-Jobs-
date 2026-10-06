"""Skill gap engine (V1.4).

Compares the candidate's skills (config/profile_skills.yaml — single source
of truth, never duplicated) against a job's requirements, classifying each
requirement MATCH / PARTIAL_MATCH / MISSING / UNKNOWN. Never invents a
candidate skill the profile doesn't actually list.

Also classifies which missing skills are worth learning (CRITICAL /
HIGH_VALUE / OPTIONAL / LOW_VALUE), driven only by their observed frequency
across logged jobs (tracking/jobs.csv) — never a fabricated "market demand".
"""
import collections
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

PARTIAL_MATCH_THRESHOLD = 0.6
MATCH_THRESHOLD = 0.92


def _candidate_skill_pool(profile=None):
    profile = profile or cfg_lib.load_profile_skills()
    skills = {s.strip().lower(): s for s in profile.get("skills", [])}
    software = {s["name"].strip().lower(): s["name"] for s in profile.get("software", [])}
    return {**skills, **software}


def classify_requirement(requirement, candidate_pool):
    """Returns one of MATCH / PARTIAL_MATCH / MISSING / UNKNOWN.

    UNKNOWN is reserved for a requirement string too vague/short to meaningfully
    compare (e.g. empty, or a single generic word) — we don't guess at it.
    """
    req = (requirement or "").strip()
    if not req:
        return "UNKNOWN"
    req_lower = req.lower()

    if len(req_lower) < 2:
        return "UNKNOWN"

    if req_lower in candidate_pool:
        return "MATCH"

    best_ratio = 0.0
    for key in candidate_pool:
        if req_lower in key or key in req_lower:
            best_ratio = max(best_ratio, 0.9)
            continue
        ratio = difflib.SequenceMatcher(None, req_lower, key).ratio()
        best_ratio = max(best_ratio, ratio)

    if best_ratio >= MATCH_THRESHOLD:
        return "MATCH"
    if best_ratio >= PARTIAL_MATCH_THRESHOLD:
        return "PARTIAL_MATCH"
    return "MISSING"


def analyze_skill_gap(requirements, profile=None):
    """requirements: list of requirement strings (from an opportunity's
    skills_required + software_required). Returns a list of
    {requirement, status} dicts, one per (deduplicated) requirement.
    """
    candidate_pool = _candidate_skill_pool(profile)
    seen = set()
    results = []
    for req in requirements or []:
        key = (req or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        results.append({"requirement": req, "status": classify_requirement(req, candidate_pool)})
    return results


def missing_skill_frequency(jobs=None):
    """Counts how often each skill/software appears across tracking/jobs.csv
    `skills_required`/`software_required` columns — this IS the only
    "market demand" signal this system ever claims, and it's always backed
    by a concrete count, never asserted abstractly.
    """
    jobs = jobs if jobs is not None else storage.read_csv(paths.JOBS_CSV)
    counter = collections.Counter()
    for j in jobs:
        for col in ("skills_required", "software_required"):
            for item in (j.get(col) or "").split(";"):
                item = item.strip()
                if item:
                    counter[item] += 1
    return counter


def learning_priority(missing_skills, jobs=None, min_frequency_for_signal=2):
    """missing_skills: iterable of skill/software names found MISSING in at
    least one opportunity. Returns a ranked list of
    {skill, frequency, priority, note}.

    priority is only ever CRITICAL/HIGH_VALUE/OPTIONAL/LOW_VALUE when the
    observed frequency actually supports it; with fewer than
    `min_frequency_for_signal` occurrences, priority is LOW_VALUE with a note
    that market-demand data is insufficient — never inflated.
    """
    frequency = missing_skill_frequency(jobs)
    results = []
    for skill in missing_skills:
        count = frequency.get(skill, 0)
        if count < min_frequency_for_signal:
            priority = "LOW_VALUE"
            note = f"Seen in only {count} logged job(s) — insufficient data to call this in-demand."
        elif count >= 5:
            priority = "CRITICAL"
            note = f"Requested in {count} logged jobs — recurring, high-impact gap."
        elif count >= 3:
            priority = "HIGH_VALUE"
            note = f"Requested in {count} logged jobs."
        else:
            priority = "OPTIONAL"
            note = f"Requested in {count} logged jobs — modest signal."
        results.append({"skill": skill, "frequency": count, "priority": priority, "note": note})

    priority_rank = {"CRITICAL": 0, "HIGH_VALUE": 1, "OPTIONAL": 2, "LOW_VALUE": 3}
    results.sort(key=lambda r: (priority_rank[r["priority"]], -r["frequency"]))
    return results
