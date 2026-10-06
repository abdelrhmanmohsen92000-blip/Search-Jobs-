"""AI job analyzer (V1.4).

Computes fit_score / quality_score / risk_score / ai_opportunity_score for a
normalized, already-scored opportunity (see scripts/lib/scoring.py). This is
a SEPARATE assessment from the V1.1 weighted `match_score` — never replaces
it, never overwrites it. Reuses the sub-scores and skill-gap data that
already exist on the opportunity rather than recomputing them from scratch.

All reasoning is grounded in fields actually present on the opportunity
(or looked up from a company record passed in) — nothing here invents a
salary, a company reputation, or a skill the candidate doesn't have.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.intelligence.skill_gap import analyze_skill_gap  # noqa: E402


def _get_sub_score(opportunity, key, default=5.0):
    sr = opportunity.get("scoring_result") or {}
    value = sr.get(key)
    return float(value) if value is not None else default


def compute_fit_score(opportunity):
    """0-100: how well the role itself fits the candidate — technical,
    experience, software, project, location, eligibility. Same inputs as
    match_score but recombined for AI-analysis purposes; intentionally not
    identical math so the two numbers are never confused for one another.
    """
    keys = ["technical", "experience", "software", "project", "location", "eligibility"]
    values = [_get_sub_score(opportunity, k) for k in keys]
    return round(sum(values) / len(values) * 10, 1)


def compute_quality_score(opportunity, company_analysis=None):
    """0-100: company quality, role/career growth value, project/market value.
    Falls back to a neutral midpoint (50) for a dimension with no evidence
    (e.g. no company record looked up) rather than penalizing or inventing a
    positive signal.
    """
    career_value = _get_sub_score(opportunity, "career_value") * 10
    compensation = _get_sub_score(opportunity, "compensation") * 10
    project = _get_sub_score(opportunity, "project") * 10
    company_fit = company_analysis.get("company_fit_score") if company_analysis else None
    company_component = float(company_fit) if company_fit is not None else 50.0
    return round((career_value + compensation + project + company_component) / 4, 1)


def compute_risk_score(opportunity, skill_gap_results=None):
    """0-100, HIGHER = MORE RISK. Built additively from concrete, named risk
    factors — never a vague "feels risky" judgment.
    """
    risk_points = 0.0
    risk_factors = []

    skill_gap_results = skill_gap_results if skill_gap_results is not None else analyze_skill_gap(
        (opportunity.get("skills_required") or []) + (opportunity.get("software_required") or [])
    )
    missing_count = sum(1 for r in skill_gap_results if r["status"] == "MISSING")
    if missing_count:
        risk_points += min(missing_count * 8, 30)
        risk_factors.append(f"{missing_count} missing skill(s)/software requirement(s)")

    if _get_sub_score(opportunity, "experience") <= 4:
        risk_points += 15
        risk_factors.append("Seniority/experience mismatch")

    if _get_sub_score(opportunity, "location") <= 4:
        risk_points += 10
        risk_factors.append("Location/work-mode restriction")

    if opportunity.get("visa_sponsorship") is None or _get_sub_score(opportunity, "eligibility") <= 4:
        risk_points += 15
        risk_factors.append("Visa/eligibility uncertain")

    if opportunity.get("salary_min") is None and opportunity.get("salary_max") is None:
        risk_points += 10
        risk_factors.append("Salary not disclosed")

    if not opportunity.get("company"):
        risk_points += 10
        risk_factors.append("Weak/missing company information")

    if opportunity.get("lifecycle_status") in ("STALE", "UNCERTAIN"):
        risk_points += 10
        risk_factors.append(f"Posting lifecycle: {opportunity.get('lifecycle_status')}")

    confidence = opportunity.get("confidence_score")
    if confidence is not None and float(confidence) < 50:
        risk_points += 10
        risk_factors.append(f"Low source-extraction confidence ({confidence})")

    return round(min(risk_points, 100), 1), risk_factors


def analyze_job(opportunity, company_analysis=None):
    """Returns {fit_score, quality_score, risk_score, risk_factors,
    ai_opportunity_score, skill_gap}. Does not touch opportunity['match_score'].
    """
    requirements = (opportunity.get("skills_required") or []) + (opportunity.get("software_required") or [])
    skill_gap_results = analyze_skill_gap(requirements)

    fit_score = compute_fit_score(opportunity)
    quality_score = compute_quality_score(opportunity, company_analysis)
    risk_score, risk_factors = compute_risk_score(opportunity, skill_gap_results)

    ai_opportunity_score = round(fit_score * 0.4 + quality_score * 0.3 + (100 - risk_score) * 0.3, 1)

    return {
        "fit_score": fit_score,
        "quality_score": quality_score,
        "risk_score": risk_score,
        "risk_factors": risk_factors,
        "ai_opportunity_score": ai_opportunity_score,
        "skill_gap": skill_gap_results,
    }
