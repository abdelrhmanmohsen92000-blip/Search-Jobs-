from scripts.application_intelligence import THRESHOLD, build_application_plan, build_plans_for_qualifying


def _opportunity(score, **overrides):
    opp = {
        "id": "abc123",
        "company": "Acme BIM Co",
        "job_title": "BIM Architect",
        "project_types": ["Residential"],
        "scoring_result": {
            "score": score,
            "matched_skills": ["BIM Coordination"],
            "missing_skills": ["Tekla Structures"],
            "strengths": ["Strong technical match"],
            "risks": [],
        },
    }
    opp.update(overrides)
    return opp


def test_build_application_plan_never_claims_missing_skills():
    opp = _opportunity(90)
    plan = build_application_plan(opp)
    joined = " ".join(plan["recommended_cv_changes"])
    assert "Do not claim" in joined
    assert "Tekla Structures" in joined


def test_build_application_plan_has_all_required_sections():
    plan = build_application_plan(_opportunity(90))
    for key in ("recommended_cv_changes", "cover_letter_requirements", "portfolio_recommendation",
                "email_strategy", "linkedin_strategy", "interview_prep_topics"):
        assert key in plan and plan[key]


def test_build_plans_for_qualifying_respects_threshold():
    opportunities = [_opportunity(95), _opportunity(79), _opportunity(50)]
    plans = build_plans_for_qualifying(opportunities)
    assert len(plans) == 1
    assert plans[0]["score"] == 95


def test_threshold_is_80():
    assert THRESHOLD == 80
