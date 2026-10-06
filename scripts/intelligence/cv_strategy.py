"""CV customization engine (V1.4).

Generates a CV_CHANGE_PLAN — guidance on what to emphasize, reorder, or
reference — never an automatically rewritten CV, and never an invented
qualification, project, or employer. Everything here is phrased as
"emphasize/reorder/highlight" over the candidate's existing, real profile
(config/profile_skills.yaml) and the specific opportunity's matched skills.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib  # noqa: E402


def generate_cv_change_plan(opportunity, job_analysis, profile=None):
    """opportunity: normalized opportunity with scoring_result.
    job_analysis: output of job_analyzer.analyze_job() (has skill_gap).

    Returns {headline, skills, experience, projects, portfolio} — each a
    short instruction string grounded in real matched data, or a neutral
    "no change needed" note when nothing stands out.
    """
    profile = profile or cfg_lib.load_profile_skills()
    matched = [r["requirement"] for r in job_analysis["skill_gap"] if r["status"] == "MATCH"]
    job_title = opportunity.get("job_title") or "this role"
    project_types = opportunity.get("project_types") or []
    profile_projects = profile.get("project_types", [])
    overlapping_projects = [p for p in project_types if p.lower() in {x.lower() for x in profile_projects}]

    headline = (
        f"Emphasize 'BIM Architect' / lead with the title closest to '{job_title}' in the CV headline, "
        f"matching this posting's own terminology." if "bim" in job_title.lower() or "architect" in job_title.lower()
        else f"Keep the current headline — it already aligns reasonably with '{job_title}'."
    )

    if matched:
        skills_plan = f"Move {', '.join(matched)} higher in the skills section — directly requested by this posting."
    else:
        skills_plan = "No specific reordering indicated — no posting-matched skills identified for this role."

    experience_plan = (
        "Emphasize multidisciplinary coordination and BIM coordination experience in the most relevant role entry."
        if any("coordination" in m.lower() for m in matched)
        else "No specific experience reordering indicated by this posting's requirements."
    )

    if overlapping_projects:
        projects_plan = f"Highlight project experience in: {', '.join(overlapping_projects)}."
        portfolio_plan = f"Lead the portfolio with a {overlapping_projects[0]} example; show a BIM coordination view first if available."
    else:
        projects_plan = "No specific project-type overlap identified — use judgement on which existing projects best represent this role."
        portfolio_plan = "No specific portfolio reordering indicated by this posting."

    return {
        "headline": headline,
        "skills": skills_plan,
        "experience": experience_plan,
        "projects": projects_plan,
        "portfolio": portfolio_plan,
    }
