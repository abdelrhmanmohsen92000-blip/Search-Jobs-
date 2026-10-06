"""V1.4 AI Intelligence Engine tests."""
import datetime as _dt

from scripts.intelligence import (
    ai_provider, career_strategy, company_analyzer, cv_strategy,
    decision_engine, job_analyzer, learning_engine, skill_gap,
)
from scripts.intelligence.application_strategy import build_strategy, portfolio_recommendation
from scripts import career_intelligence


def _opportunity(**overrides):
    opp = {
        "id": "abc123", "company": "Acme BIM Co", "job_title": "BIM Coordinator",
        "country": "United Arab Emirates", "match_score": 82.5, "priority": "STRONG",
        "employment_type": "Full-time", "source_url": "https://indeed.com/1",
        "skills_required": ["BIM Coordination"], "software_required": ["Autodesk Revit"],
        "project_types": ["Residential"], "visa_sponsorship": True,
        "salary_min": None, "salary_max": None, "confidence_score": 80, "lifecycle_status": "NEW",
        "scoring_result": {
            "score": 82.5, "priority": "STRONG", "recommendation": "APPLY", "action": "APPLY",
            "technical": 9, "experience": 8, "software": 9, "project": 8, "location": 7,
            "eligibility": 9, "career_value": 7, "compensation": 6,
            "matched_skills": ["BIM Coordination", "Autodesk Revit"], "missing_skills": [],
            "strengths": ["Strong match"], "risks": [],
        },
    }
    opp.update(overrides)
    if "match_score" in overrides and "scoring_result" not in overrides:
        opp["scoring_result"] = {**opp["scoring_result"], "score": overrides["match_score"]}
    return opp


# --- AI provider abstraction / rule-based fallback -------------------------------

def test_rule_based_provider_requires_no_api_key():
    provider = ai_provider.RuleBasedAIProvider()
    result = provider.analyze("test prompt", {"a": 1})
    assert result["provider"] == "rule_based"


def test_get_ai_provider_defaults_to_rule_based_without_config():
    provider = ai_provider.get_ai_provider({})
    assert isinstance(provider, ai_provider.RuleBasedAIProvider)


def test_get_ai_provider_unimplemented_falls_back_safely():
    provider = ai_provider.get_ai_provider({"provider": "openai", "providers": {"openai": {"implemented": False}}})
    result = provider.analyze("x")
    assert result["status"] == "NOT_IMPLEMENTED"
    assert result["provider"] == "openai"


def test_ai_provider_base_class_requires_implementation():
    import pytest
    with pytest.raises(NotImplementedError):
        ai_provider.AIProvider().analyze("x")


def test_tier_for_score_bands():
    assert ai_provider.tier_for_score(95) == 4
    assert ai_provider.tier_for_score(87) == 3
    assert ai_provider.tier_for_score(72) == 2
    assert ai_provider.tier_for_score(40) == 1
    assert ai_provider.tier_for_score(None) == 1


# --- Job analysis ------------------------------------------------------------------

def test_job_analyzer_returns_separate_fit_quality_risk_and_overall_score():
    opp = _opportunity()
    analysis = job_analyzer.analyze_job(opp)
    assert set(analysis) == {"fit_score", "quality_score", "risk_score", "risk_factors", "ai_opportunity_score", "skill_gap"}
    assert 0 <= analysis["fit_score"] <= 100
    assert 0 <= analysis["ai_opportunity_score"] <= 100


def test_job_analyzer_never_overwrites_match_score():
    opp = _opportunity(match_score=82.5)
    job_analyzer.analyze_job(opp)
    assert opp["match_score"] == 82.5  # untouched


def test_job_analyzer_flags_missing_salary_as_risk():
    opp = _opportunity(salary_min=None, salary_max=None)
    analysis = job_analyzer.analyze_job(opp)
    assert any("Salary not disclosed" in f for f in analysis["risk_factors"])


def test_job_analyzer_lower_risk_with_disclosed_salary():
    opp_no_salary = _opportunity(salary_min=None, salary_max=None)
    opp_with_salary = _opportunity(salary_min=50000, salary_max=70000)
    risk_no = job_analyzer.analyze_job(opp_no_salary)["risk_score"]
    risk_with = job_analyzer.analyze_job(opp_with_salary)["risk_score"]
    assert risk_with < risk_no


def test_job_analyzer_flags_stale_lifecycle_as_risk():
    opp = _opportunity(lifecycle_status="STALE")
    analysis = job_analyzer.analyze_job(opp)
    assert any("STALE" in f for f in analysis["risk_factors"])


# --- Skill gap engine ---------------------------------------------------------------

def test_skill_gap_match_for_known_candidate_skill():
    profile = {"skills": ["BIM Coordination"], "software": [{"name": "Autodesk Revit"}]}
    results = skill_gap.analyze_skill_gap(["BIM Coordination", "Autodesk Revit"], profile=profile)
    assert all(r["status"] == "MATCH" for r in results)


def test_skill_gap_missing_for_unrelated_requirement():
    profile = {"skills": ["BIM Coordination"], "software": []}
    results = skill_gap.analyze_skill_gap(["Tekla Structures"], profile=profile)
    assert results[0]["status"] == "MISSING"


def test_skill_gap_unknown_for_empty_requirement():
    assert skill_gap.classify_requirement("", {}) == "UNKNOWN"


def test_skill_gap_never_invents_candidate_skills():
    # profile has nothing — every requirement must be MISSING or UNKNOWN, never MATCH
    profile = {"skills": [], "software": []}
    results = skill_gap.analyze_skill_gap(["Revit", "Navisworks", "BIM Coordination"], profile=profile)
    assert all(r["status"] != "MATCH" for r in results)


def test_learning_priority_requires_minimum_frequency_for_high_value():
    jobs = [{"skills_required": "Dynamo", "software_required": ""}] * 1  # only 1 occurrence
    priorities = skill_gap.learning_priority(["Dynamo"], jobs=jobs)
    assert priorities[0]["priority"] == "LOW_VALUE"
    assert "insufficient" in priorities[0]["note"].lower()


def test_learning_priority_critical_with_strong_signal():
    jobs = [{"skills_required": "Dynamo;IFC", "software_required": ""}] * 5
    priorities = skill_gap.learning_priority(["Dynamo"], jobs=jobs)
    assert priorities[0]["priority"] == "CRITICAL"
    assert priorities[0]["frequency"] == 5


# --- Decision engine -----------------------------------------------------------------

def test_decision_apply_now_for_high_score_low_risk():
    opp = _opportunity(match_score=92)
    analysis = job_analyzer.analyze_job(opp)
    result = decision_engine.decide(opp, analysis)
    assert result["decision"] == "APPLY_NOW"
    assert result["why"]
    assert result["next_action"]


def test_decision_skip_for_very_low_score():
    opp = _opportunity(match_score=10)
    analysis = job_analyzer.analyze_job(opp)
    result = decision_engine.decide(opp, analysis)
    assert result["decision"] == "SKIP"


def test_decision_network_first_for_hidden_opportunity_with_moderate_score():
    opp = _opportunity(match_score=55)
    analysis = job_analyzer.analyze_job(opp)
    company_analysis = {"potential_hidden_opportunity": True, "company_fit_score": 60}
    result = decision_engine.decide(opp, analysis, company_analysis)
    assert result["decision"] == "NETWORK_FIRST"


def test_decision_result_is_always_one_of_allowed_values():
    for score in (10, 30, 55, 75, 92):
        opp = _opportunity(match_score=score)
        analysis = job_analyzer.analyze_job(opp)
        result = decision_engine.decide(opp, analysis)
        assert result["decision"] in decision_engine.DECISIONS


def test_action_priority_is_bounded_and_numeric():
    opp = _opportunity(match_score=92)
    analysis = job_analyzer.analyze_job(opp)
    decision = decision_engine.decide(opp, analysis)
    priority = decision_engine.compute_action_priority(opp, analysis, decision)
    assert 0 <= priority <= 100


def test_record_decision_appends_to_csv(tmp_path):
    csv_path = tmp_path / "decisions.csv"
    opp = _opportunity(match_score=92)
    analysis = job_analyzer.analyze_job(opp)
    decision = decision_engine.decide(opp, analysis)
    priority = decision_engine.compute_action_priority(opp, analysis, decision)
    decision_engine.record_decision(opp, analysis, decision, priority, csv_path=csv_path)
    content = csv_path.read_text(encoding="utf-8")
    assert "Acme BIM Co" in content
    assert decision["decision"] in content


# --- Company analysis -----------------------------------------------------------------

def test_company_priority_bands():
    assert company_analyzer.company_priority(90) == "A+"
    assert company_analyzer.company_priority(75) == "A"
    assert company_analyzer.company_priority(55) == "B"
    assert company_analyzer.company_priority(35) == "C"
    assert company_analyzer.company_priority(10) == "D"


def test_analyze_company_unknown_dimensions_stay_unknown():
    record = {"company_name": "Acme", "ai_fit_score": "40.0", "category": "LOW_PRIORITY"}
    analysis = company_analyzer.analyze_company(record, contacts=[])
    assert analysis["market_reputation"] == "UNKNOWN"
    assert analysis["international_activity"] == "UNKNOWN"
    assert "DATA_INSUFFICIENT" in analysis["likely_hiring_managers"][0]


def test_analyze_company_hidden_opportunity_flag():
    record = {"company_name": "Acme", "ai_fit_score": "60.0", "category": "HIDDEN_OPPORTUNITY", "bim_activity": "growing team"}
    analysis = company_analyzer.analyze_company(record, contacts=[])
    assert analysis["potential_hidden_opportunity"] is True
    assert "NETWORK_FIRST" in analysis["recommended_networking_action"]


def test_analyze_company_finds_logged_contacts():
    record = {"company_name": "Acme", "ai_fit_score": "60.0", "category": "OPEN_VACANCY"}
    contacts = [{"company": "Acme", "person": "Jane Doe"}]
    analysis = company_analyzer.analyze_company(record, contacts=contacts)
    assert analysis["likely_hiring_managers"] == ["Jane Doe"]


# --- CV strategy (never invents experience) --------------------------------------------

def test_cv_change_plan_has_all_sections():
    opp = _opportunity()
    analysis = job_analyzer.analyze_job(opp)
    plan = cv_strategy.generate_cv_change_plan(opp, analysis)
    assert set(plan) == {"headline", "skills", "experience", "projects", "portfolio"}


def test_cv_change_plan_only_references_matched_skills():
    opp = _opportunity()
    analysis = job_analyzer.analyze_job(opp)
    plan = cv_strategy.generate_cv_change_plan(opp, analysis)
    for matched in analysis["skill_gap"]:
        if matched["status"] == "MATCH":
            assert matched["requirement"] in plan["skills"]


# --- Application strategy / portfolio intelligence --------------------------------------

def test_portfolio_recommendation_insufficient_without_project_metadata():
    profile = {"project_types": ["Residential"]}  # no portfolio_projects key
    result = portfolio_recommendation(_opportunity(), profile=profile)
    assert result == "PORTFOLIO_DATA_INSUFFICIENT"


def test_build_strategy_marks_high_value_at_90_plus():
    opp = _opportunity(match_score=94)
    analysis = job_analyzer.analyze_job(opp)
    decision = decision_engine.decide(opp, analysis)
    cv_plan = cv_strategy.generate_cv_change_plan(opp, analysis)
    strategy = build_strategy(opp, analysis, cv_plan, decision)
    assert strategy["high_value_application"] is True


def test_build_strategy_not_high_value_below_90():
    opp = _opportunity(match_score=82)
    analysis = job_analyzer.analyze_job(opp)
    strategy = build_strategy(opp, analysis)
    assert strategy["high_value_application"] is False


# --- Learning engine (sample-size honesty) --------------------------------------------

def test_learning_engine_flags_insufficient_sample():
    applications = [{"country": "Germany", "status": "APPLIED"}]
    result = learning_engine.response_rate_by("country", applications)
    assert result["Germany"]["insufficient_sample"] is True
    assert result["Germany"]["sample_size"] == 1


def test_learning_engine_sufficient_sample_not_flagged():
    applications = [{"country": "Germany", "status": "INTERVIEW"}] * 3 + [{"country": "Germany", "status": "APPLIED"}]
    result = learning_engine.response_rate_by("country", applications)
    assert result["Germany"]["sample_size"] == 4
    assert result["Germany"]["insufficient_sample"] is False


def test_learning_engine_never_computes_rate_without_denominator():
    applications = [{"country": "Germany", "status": "NEW"}]  # NEW is not an "applied" status
    result = learning_engine.response_rate_by("country", applications)
    assert result == {}  # no denominator -> no fabricated rate


def test_full_learning_report_includes_networking():
    report = learning_engine.full_learning_report(applications=[], networking=[])
    assert report["networking_response_rate"]["sample_size"] == 0


# --- Market intelligence (sample size + confidence) -------------------------------------

def test_market_intelligence_reports_sample_size_and_confidence():
    jobs = [{"skills_required": "Revit", "software_required": "", "job_title": "BIM Architect",
             "country": "Germany", "remote": "False", "employment_type": "Full-time"}]
    result = career_strategy.market_intelligence(jobs=jobs)
    assert result["sample_size"] == 1
    assert result["confidence"] == "LOW"


def test_market_intelligence_empty_is_honest():
    result = career_strategy.market_intelligence(jobs=[])
    assert result["sample_size"] == 0
    assert result["confidence"] == "LOW"
    assert result["most_requested_skills"] == []


def test_market_intelligence_never_fabricates_salary_pattern():
    jobs = [{"skills_required": "", "software_required": "", "job_title": "X", "country": "Y",
             "remote": "", "employment_type": ""}]
    result = career_strategy.market_intelligence(jobs=jobs)
    assert result["salary_pattern"] == "DATA_INSUFFICIENT"


# --- Alerts -------------------------------------------------------------------------------

def test_generate_alerts_fires_exceptional_opportunity(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib
    empty_csv = tmp_path / "applications.csv"
    empty_csv.write_text("status\n", encoding="utf-8")
    monkeypatch.setattr(paths_lib, "APPLICATIONS_CSV", empty_csv)
    monkeypatch.setattr(paths_lib, "ALERTS_CSV", tmp_path / "alerts.csv")
    monkeypatch.setattr(paths_lib, "DATA_DIR", tmp_path)

    opp = _opportunity(match_score=95, priority="EXCEPTIONAL")
    analysis = job_analyzer.analyze_job(opp)
    enriched = [{**opp, "job_analysis": analysis, "company_analysis": None,
                 "decision": decision_engine.decide(opp, analysis), "action_priority": 95}]
    alerts = career_intelligence.generate_alerts(enriched)
    assert any(a["alert_type"] == "NEW_EXCEPTIONAL_OPPORTUNITY" for a in alerts)


def test_generate_alerts_no_fake_alerts_on_empty_input(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib
    empty_csv = tmp_path / "applications.csv"
    empty_csv.write_text("status\n", encoding="utf-8")
    monkeypatch.setattr(paths_lib, "APPLICATIONS_CSV", empty_csv)
    monkeypatch.setattr(paths_lib, "ALERTS_CSV", tmp_path / "alerts.csv")
    monkeypatch.setattr(paths_lib, "DATA_DIR", tmp_path)
    alerts = career_intelligence.generate_alerts([])
    assert alerts == []


# --- AI tiering / cost control via career_intelligence.analyze_opportunities -----------

def test_analyze_opportunities_skips_tier1_without_deep():
    low = _opportunity(match_score=40)
    high = _opportunity(match_score=85, id="high1")
    enriched = career_intelligence.analyze_opportunities([low, high], score_min=0, deep=False)
    ids = {o["id"] for o in enriched}
    assert "high1" in ids
    assert low["id"] not in ids  # tier 1 (below 70) skipped without --deep


def test_analyze_opportunities_deep_includes_everything():
    low = _opportunity(match_score=40)
    enriched = career_intelligence.analyze_opportunities([low], score_min=0, deep=True)
    assert len(enriched) == 1


def test_analyze_opportunities_respects_score_min():
    low = _opportunity(match_score=40)
    high = _opportunity(match_score=85, id="high1")
    enriched = career_intelligence.analyze_opportunities([low, high], score_min=80, deep=True)
    assert len(enriched) == 1
    assert enriched[0]["id"] == "high1"


def test_analyze_opportunities_sorted_by_action_priority_desc():
    a = _opportunity(match_score=75, id="a")
    b = _opportunity(match_score=95, id="b")
    enriched = career_intelligence.analyze_opportunities([a, b], score_min=0, deep=True)
    priorities = [o["action_priority"] for o in enriched]
    assert priorities == sorted(priorities, reverse=True)


# --- Missing profile data / UNKNOWN handling ---------------------------------------------

def test_job_analyzer_handles_missing_profile_gracefully(monkeypatch):
    opp = _opportunity(skills_required=[], software_required=[])
    analysis = job_analyzer.analyze_job(opp)
    assert analysis["skill_gap"] == []  # no requirements -> nothing to gap-analyze, not fabricated


def test_company_analyzer_handles_missing_fields():
    record = {"company_name": "Acme"}  # minimal record
    analysis = company_analyzer.analyze_company(record, contacts=[])
    assert analysis["hiring_activity"] == "UNKNOWN"
    assert analysis["bim_maturity"] == "UNKNOWN"


# --- No-fake-intelligence policy ----------------------------------------------------------

def test_decision_engine_never_fabricates_why_for_low_match():
    # no genuinely matched skills and low sub-scores — nothing positive to honestly cite
    opp = _opportunity(match_score=15, skills_required=["Tekla Structures"], software_required=["Rhino"],
                        scoring_result={
                            "score": 15, "priority": "LOW", "recommendation": "WATCH", "action": "SKIP",
                            "technical": 2, "experience": 2, "software": 2, "project": 2, "location": 2,
                            "eligibility": 2, "career_value": 2, "compensation": 2,
                            "matched_skills": [], "missing_skills": ["Tekla Structures"], "strengths": [], "risks": [],
                        })
    analysis = job_analyzer.analyze_job(opp)
    result = decision_engine.decide(opp, analysis)
    assert result["why"]  # always has a reason, grounded in actual score/risk numbers
    assert "15" in result["why"][0] or "risk" in result["why"][0].lower()


def test_cv_strategy_never_claims_overlap_without_evidence():
    opp = _opportunity(project_types=["Healthcare"])  # not in default profile skills fixture
    profile = {"project_types": ["Residential"], "skills": [], "software": []}
    analysis = job_analyzer.analyze_job(opp)
    plan = cv_strategy.generate_cv_change_plan(opp, analysis, profile=profile)
    assert "No specific project-type overlap" in plan["projects"]
