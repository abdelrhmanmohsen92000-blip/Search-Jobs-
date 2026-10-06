"""Application strategy engine (V1.4).

Wraps scripts/application_intelligence.py (V1.2 — CV/cover-letter/portfolio/
interview guidance for score >= 80) rather than duplicating it, adding the
V1.4 HIGH-VALUE flag for score >= 90 and honest portfolio-data gating
(Phase 14): the repository has no per-project portfolio metadata file today
(config/profile_skills.yaml only lists project *types*, not individual named
projects), so portfolio_recommendation() always reports
PORTFOLIO_DATA_INSUFFICIENT rather than inventing project names.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib  # noqa: E402
from scripts.application_intelligence import THRESHOLD, build_application_plan  # noqa: E402

HIGH_VALUE_THRESHOLD = 90


def portfolio_recommendation(opportunity, profile=None):
    """Returns either a list of {project, why_relevant, priority} (only
    possible once real per-project metadata exists) or the literal string
    'PORTFOLIO_DATA_INSUFFICIENT' when it doesn't — which is always, today.
    """
    profile = profile or cfg_lib.load_profile_skills()
    if not profile.get("portfolio_projects"):
        return "PORTFOLIO_DATA_INSUFFICIENT"

    project_types = {p.lower() for p in (opportunity.get("project_types") or [])}
    results = []
    for project in profile["portfolio_projects"]:
        overlap = project_types & {t.lower() for t in project.get("project_types", [])}
        if overlap:
            results.append({
                "project": project.get("name"),
                "why_relevant": f"Matches project type(s): {', '.join(overlap)}",
                "priority": "HIGH" if len(overlap) > 1 else "MEDIUM",
            })
    return results or "PORTFOLIO_DATA_INSUFFICIENT"


_OPTIONAL_COMPLETENESS_FIELDS = (
    "location", "area_sqm", "role", "responsibilities", "bim_level", "disciplines", "deliverables", "achievements",
)


def _project_evidence(opportunity, project):
    """Returns (evidence_strings, dimension_count). Every evidence string is
    grounded in an actual overlap between the opportunity's stated
    requirements and the project's own recorded facts — never inferred.
    """
    evidence = []
    opp_types = {t.lower() for t in (opportunity.get("project_types") or [])}
    proj_types = {t.lower() for t in (project.get("project_types") or [])}
    type_overlap = opp_types & proj_types
    if type_overlap:
        evidence.append(f"project type(s): {', '.join(sorted(type_overlap))}")

    opp_software = {s.lower() for s in (opportunity.get("software_required") or [])}
    proj_software = {s.lower() for s in (project.get("software") or [])}
    software_overlap = opp_software & proj_software
    if software_overlap:
        evidence.append(f"software: {', '.join(sorted(software_overlap))}")

    opp_skills = {s.lower() for s in (opportunity.get("skills_required") or [])}
    proj_disciplines = {d.lower() for d in (project.get("disciplines") or [])}
    discipline_overlap = opp_skills & proj_disciplines
    if discipline_overlap:
        evidence.append(f"disciplines/skills: {', '.join(sorted(discipline_overlap))}")

    dimension_count = sum(1 for overlap in (type_overlap, software_overlap, discipline_overlap) if overlap)
    return evidence, dimension_count


def _project_confidence(project):
    """Confidence reflects how complete the project's own recorded metadata
    is — a project entry that is mostly UNKNOWN/empty can't support a
    high-confidence match even if the few fields it has line up.
    """
    filled = sum(1 for f in _OPTIONAL_COMPLETENESS_FIELDS if project.get(f) not in (None, "", [], "UNKNOWN"))
    if filled >= 4:
        return "HIGH"
    if filled >= 2:
        return "MEDIUM"
    return "LOW"


def match_portfolio_projects(opportunity, profile=None):
    """PORTFOLIO_MATCH (production audit Phase 2, §3): for each real project
    in profile['portfolio_projects'], returns evidence-backed overlap with
    the opportunity's stated requirements:
        {project, evidence: [...], relevance: HIGH/MEDIUM/LOW, confidence: HIGH/MEDIUM/LOW}

    relevance is driven purely by how many independent evidence dimensions
    overlap (project type / software / disciplines) — never by a vague
    similarity score. Returns the literal string 'PORTFOLIO_DATA_INSUFFICIENT'
    when there is no portfolio data OR no project has any evidence at all —
    never a fabricated match.
    """
    profile = profile or cfg_lib.load_profile_skills()
    projects = profile.get("portfolio_projects")
    if not projects:
        return "PORTFOLIO_DATA_INSUFFICIENT"

    matches = []
    for project in projects:
        evidence, dimension_count = _project_evidence(opportunity, project)
        if not evidence:
            continue
        relevance = "HIGH" if dimension_count >= 2 else "MEDIUM" if dimension_count == 1 else "LOW"
        matches.append({
            "project": project.get("name"),
            "evidence": evidence,
            "relevance": relevance,
            "confidence": _project_confidence(project),
        })

    if not matches:
        return "PORTFOLIO_DATA_INSUFFICIENT"

    relevance_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    matches.sort(key=lambda m: relevance_rank[m["relevance"]])
    return matches


def build_strategy(opportunity, job_analysis, cv_plan=None, decision_result=None):
    """Full application strategy for one opportunity. Only meaningful for
    score >= THRESHOLD (80) per V1.2/V1.4 — callers should gate on that
    (see ai_provider.tier_for_score) before calling this for cost control.
    """
    plan = build_application_plan(opportunity)
    score = plan.get("score") or 0

    return {
        **plan,
        "high_value_application": score >= HIGH_VALUE_THRESHOLD,
        "cv_change_plan": cv_plan,
        "portfolio_recommendation": portfolio_recommendation(opportunity),
        "portfolio_matches": match_portfolio_projects(opportunity),
        "decision": decision_result.get("decision") if decision_result else None,
        "next_action": decision_result.get("next_action") if decision_result else None,
    }
