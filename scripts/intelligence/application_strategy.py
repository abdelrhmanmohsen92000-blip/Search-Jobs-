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
        "decision": decision_result.get("decision") if decision_result else None,
        "next_action": decision_result.get("next_action") if decision_result else None,
    }
