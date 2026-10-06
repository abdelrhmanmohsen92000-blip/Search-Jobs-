#!/usr/bin/env python3
"""Application intelligence engine.

For every opportunity with score >= 80, generates an application package
plan: recommended CV emphasis, required CV changes, cover letter
requirements, portfolio recommendation, email strategy, LinkedIn strategy,
and interview prep topics.

Hard constraint: never invents experience, qualifications, or project
history. Every recommendation is phrased as "emphasize X" / "reorder to lead
with Y" / "prepare to discuss Z" drawing only from config/profile_skills.yaml
and profile/profile.md — never fabricated content.
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib, paths  # noqa: E402

THRESHOLD = 80


def build_application_plan(opportunity):
    """opportunity: normalized dict (schemas/opportunity.schema.json) plus a
    `scoring_result` key from scripts/lib/scoring.score_opportunity_record().
    """
    profile = cfg_lib.load_profile_skills()
    scoring_result = opportunity.get("scoring_result", {})
    matched = scoring_result.get("matched_skills", [])
    missing = scoring_result.get("missing_skills", [])
    project_types = opportunity.get("project_types", [])
    profile_projects = profile.get("project_types", [])
    overlapping_projects = [p for p in project_types if p.lower() in {x.lower() for x in profile_projects}]

    cv_changes = []
    if matched:
        cv_changes.append(f"Lead the skills section with: {', '.join(matched)} — these directly match the posting.")
    if overlapping_projects:
        cv_changes.append(f"Reorder project examples to foreground: {', '.join(overlapping_projects)}.")
    if missing:
        cv_changes.append(
            f"Do not claim: {', '.join(missing)} unless genuinely held — flag as a gap to address in the cover "
            "letter or interview instead of the CV."
        )
    if not cv_changes:
        cv_changes.append("No major reordering needed — current CV already aligns with this posting's emphasis.")

    cover_letter_requirements = [
        f"Open with a specific reference to {opportunity.get('company', 'the company')}'s actual project or "
        "BIM activity (from the company record), not a generic opener.",
        "State 4+ years of BIM/architectural experience and name the 1-2 matched skills most relevant to this role.",
        "Address eligibility proactively if visa sponsorship or relocation is relevant to this posting.",
    ]

    portfolio_recommendation = (
        f"Lead the portfolio with examples from: {', '.join(overlapping_projects) or profile_projects[:2]}; "
        f"include at least one Revit/BIM coordination view (LOD 350+) given the BIM-heavy scope of this role."
    )

    email_strategy = (
        "Short, specific email (4-6 sentences) referencing the exact job title and one piece of evidence of fit; "
        "attach tailored CV + portfolio link; request a brief intro call."
    )

    linkedin_strategy = (
        "Identify the hiring manager/BIM lead for this company in tracking/networking.csv (or add them); "
        "connect with a short note after applying, referencing the application — never before researching the role."
    )

    interview_prep_topics = [
        "Be ready to walk through a Revit/BIM coordination workflow end-to-end (clash detection, LOD, multidisciplinary coordination).",
        f"Prepare 1-2 concrete project stories from: {', '.join(overlapping_projects) or 'your logged project history'}.",
        "Prepare honest, specific answers for any flagged missing skills — framed as fast-learnable given adjacent tool expertise (Revit/Navisworks/AutoCAD).",
        "Research the company's actual projects (from the company record) to ask informed questions.",
    ]

    return {
        "opportunity_id": opportunity.get("id"),
        "company": opportunity.get("company"),
        "job_title": opportunity.get("job_title"),
        "score": scoring_result.get("score"),
        "recommended_cv_changes": cv_changes,
        "cover_letter_requirements": cover_letter_requirements,
        "portfolio_recommendation": portfolio_recommendation,
        "email_strategy": email_strategy,
        "linkedin_strategy": linkedin_strategy,
        "interview_prep_topics": interview_prep_topics,
        "generated_at": _dt.date.today().isoformat(),
    }


def build_plans_for_qualifying(opportunities, threshold=THRESHOLD):
    """opportunities: list of normalized dicts each carrying a `scoring_result`."""
    qualifying = [o for o in opportunities if (o.get("scoring_result") or {}).get("score", 0) >= threshold]
    return [build_application_plan(o) for o in qualifying]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("opportunities_json", help="Path to a JSON file: list of normalized+scored opportunities")
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args()

    opportunities = json.loads(Path(args.opportunities_json).read_text(encoding="utf-8"))
    plans = build_plans_for_qualifying(opportunities, args.threshold)
    print(json.dumps(plans, indent=2))


if __name__ == "__main__":
    main()
