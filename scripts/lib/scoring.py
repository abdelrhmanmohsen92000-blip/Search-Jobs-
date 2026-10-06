"""Opportunity scoring engine (V1.1).

Upgrades the original 7-criterion / 100-point model (docs/scoring-model.md v1)
to the 8-criterion model requested for V1.1:

    Technical Match        25
    Experience Match       20
    Software Match         15
    Project Match          10
    Location / Work Mode   10
    Eligibility            10
    Career Value            5
    Compensation Potential  5
    -----------------------------
    Total                  100

Each sub-score is 0-10 (as before); the weighted sum is scaled to 0-100.
This module is the single implementation; scripts/score_opportunity.py (the
original CLI) now delegates here for backward compatibility.
"""
from . import config as cfg_lib

WEIGHTS = {
    "technical": 25,
    "experience": 20,
    "software": 15,
    "project": 10,
    "location": 10,
    "eligibility": 10,
    "career_value": 5,
    "compensation": 5,
}

PRIORITY_BANDS = [
    (90, "EXCEPTIONAL"),
    (75, "STRONG"),
    (60, "GOOD"),
    (40, "MODERATE"),
    (0, "LOW"),
]

RECOMMENDATION_BANDS = [
    (85, "APPLY_NOW"),
    (70, "APPLY"),
    (50, "CONSIDER"),
    (0, "WATCH"),
]


def _band(score, bands):
    for threshold, label in bands:
        if score >= threshold:
            return label
    return bands[-1][1]


def priority_for_score(score):
    return _band(score, PRIORITY_BANDS)


def recommendation_for_score(score):
    return _band(score, RECOMMENDATION_BANDS)


def compute_weighted_score(sub_scores):
    """sub_scores: dict with the 8 WEIGHTS keys, each 0-10. Returns 0-100 float."""
    missing = set(WEIGHTS) - set(sub_scores)
    if missing:
        raise ValueError(f"Missing sub-scores: {sorted(missing)}")
    total = 0.0
    for key, weight in WEIGHTS.items():
        value = sub_scores[key]
        if not 0 <= value <= 10:
            raise ValueError(f"{key} must be between 0 and 10, got {value}")
        total += (value / 10) * weight
    return round(total, 1)


def _normalize_list(items):
    return {str(x).strip().lower() for x in (items or []) if str(x).strip()}


def skill_gap(required_skills, required_software, profile=None):
    """Compare a posting's required skills/software against the profile.

    Returns (matched, missing) as sorted lists of strings (original casing
    from the requirement lists, deduplicated case-insensitively).
    """
    profile = cfg_lib.load_profile_skills() if profile is None else profile
    profile_skills = _normalize_list(profile.get("skills", []))
    profile_software = _normalize_list(s["name"] for s in profile.get("software", []))
    have = profile_skills | profile_software

    matched, missing = [], []
    seen = set()
    for item in list(required_skills or []) + list(required_software or []):
        key = str(item).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if key in have:
            matched.append(item)
        else:
            missing.append(item)
    return matched, missing


def build_strengths_and_risks(sub_scores, matched, missing, opportunity=None):
    strengths, risks = [], []
    opportunity = opportunity or {}

    if sub_scores.get("technical", 0) >= 8:
        strengths.append("Strong technical/domain match with BIM and architectural core skills.")
    if sub_scores.get("software", 0) >= 8:
        strengths.append("Required software overlaps heavily with Revit/Navisworks/AutoCAD expertise.")
    if sub_scores.get("eligibility", 0) >= 8:
        strengths.append("Eligibility (visa/work authorization) looks favorable.")
    if sub_scores.get("location", 0) >= 8:
        strengths.append("Work mode/location fits stated openness to remote, hybrid, on-site, and relocation.")
    if matched:
        strengths.append(f"Matched skills/software: {', '.join(matched)}.")

    if sub_scores.get("experience", 0) <= 4:
        risks.append("Experience requirement is significantly mismatched (over- or under-qualified ask).")
    if sub_scores.get("eligibility", 0) <= 4:
        risks.append("Eligibility is uncertain — visa sponsorship or work authorization unclear/unfavorable.")
    if missing:
        risks.append(f"Missing/unconfirmed skills or software: {', '.join(missing)}.")
    if opportunity.get("risk_flags"):
        risks.extend(opportunity["risk_flags"])
    if not opportunity.get("source_url"):
        risks.append("No source URL recorded — verify the listing is still live before applying.")

    return strengths, risks


def score_opportunity_record(opportunity, sub_scores, profile=None):
    """Full scoring result for one opportunity.

    opportunity: dict with at least skills_required/software_required/risk_flags/source_url
    sub_scores: dict with the 8 weighted sub-scores (0-10 each)

    Returns a dict:
        score, priority, recommendation, matched_skills, missing_skills,
        strengths, risks
    """
    score = compute_weighted_score(sub_scores)
    matched, missing = skill_gap(
        opportunity.get("skills_required"), opportunity.get("software_required"), profile=profile
    )
    strengths, risks = build_strengths_and_risks(sub_scores, matched, missing, opportunity)
    return {
        "score": score,
        "priority": priority_for_score(score),
        "recommendation": recommendation_for_score(score),
        "matched_skills": matched,
        "missing_skills": missing,
        "strengths": strengths,
        "risks": risks,
    }
