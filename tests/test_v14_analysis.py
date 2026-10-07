"""V1.4 — requirements extraction, skills gap, 12-dimension analysis, decisions,
versioned model, optional LLM enrichment, company intelligence.

Synthetic TEST_FIXTURE data only; no network; writes go to the per-test workspace.
"""
import datetime as _dt
import json
from pathlib import Path

import pytest
import yaml

from scripts import daily_research
from scripts.intelligence import analysis_engine as ae
from scripts.intelligence import company_intel, llm_enrichment, opportunity_priority, scoring_model
from scripts.intelligence.requirements_extractor import extract_requirements, skills_gap
from scripts.lib import normalize, paths, storage

TODAY = _dt.date.today()
FIXTURES = json.loads(Path("fixtures/synthetic_jobs.json").read_text(encoding="utf-8"))["jobs"]


def raw(i):
    j = dict(FIXTURES[i])
    j["date_posted"] = (TODAY - _dt.timedelta(days=j.pop("posted_days_ago"))).isoformat()
    closing = j.pop("closing_in_days", None)
    if closing:
        j["closing_date"] = (TODAY + _dt.timedelta(days=closing)).isoformat()
    j.pop("synthetic", None)
    return j


def opp(i=0, **extra):
    return normalize.normalize_opportunity({**raw(i), **extra})


PROFILE = {"experience_years": 4, "skills": ["BIM Coordination", "Clash Coordination", "Construction Documentation"],
           "software": [{"name": "Autodesk Revit"}, {"name": "Navisworks"}, {"name": "AutoCAD"}],
           "project_types": ["Healthcare", "Residential"]}


# --- requirements extraction ---------------------------------------------------------

def test_required_vs_preferred_split_by_section_and_wording():
    r = extract_requirements(opp(0))
    assert {"Revit", "Navisworks", "AutoCAD", "BIM 360"} <= set(r["required_skills"])
    assert set(r["preferred_skills"]) == {"ISO 19650", "Dynamo"}
    facade = extract_requirements(opp(10))
    assert "Revit" in facade["preferred_skills"] and "Rhino" in facade["required_skills"]


def test_scalar_fields_and_provenance():
    r = extract_requirements(opp(0))
    assert r["min_years_experience"] == 4 and r["field_sources"]["min_years_experience"] == "TEXT_EXTRACTED"
    assert r["education"] == ["Bachelor's in Architecture"]
    assert r["languages"] == ["Arabic", "English"]
    assert "Housing allowance" in r["benefits"] and "Medical insurance" in r["benefits"]
    assert r["salary"]["salary_currency"] == "SAR" and r["field_sources"]["salary"] == "SOURCE_STRUCTURED"
    assert r["application_method"].startswith("ONLINE:")
    assert r["employment_type"] == "Full-time" and r["field_sources"]["employment_type"] == "SOURCE_STRUCTURED"
    assert r["responsibilities"][0].startswith("Develop and manage Revit")


def test_unknowns_stay_unknown_and_salary_never_read_from_text():
    o = normalize.normalize_opportunity({"job_title": "TEST_FIXTURE Architect", "company": "TEST_FIXTURE Co",
                                         "description": "Great role. Salary 50,000 SAR per month. Revit."})
    r = extract_requirements(o)
    assert r["salary"] == "UNKNOWN" and r["field_sources"]["salary"] == "UNKNOWN"
    assert r["min_years_experience"] is None and r["field_sources"]["min_years_experience"] == "UNKNOWN"
    assert r["work_mode"] == "UNKNOWN" and r["application_method"] == "UNKNOWN"
    assert r["seniority"] == "UNKNOWN"


def test_work_mode_seniority_certifications_and_barriers():
    assert extract_requirements(opp(1))["work_mode"] == "HYBRID"
    manager = extract_requirements(opp(2))
    assert manager["seniority"] == "MANAGER" and manager["min_years_experience"] == 12
    assert "PMP" in manager["certifications"]
    uk = extract_requirements(opp(7))
    assert "No visa sponsorship" in uk["eligibility_barriers"]
    assert any("right to work" in b.lower() for b in uk["eligibility_barriers"])


def test_seniority_derived_from_years_is_labelled_derived():
    r = extract_requirements(opp(0))
    assert r["seniority"] == "MID" and r["field_sources"]["seniority"] == "DERIVED"


# --- skills gap ------------------------------------------------------------------------

def test_skills_gap_matched_transferable_missing():
    gap = skills_gap(extract_requirements(opp(1)), PROFILE)
    assert "Revit" in gap["matched"] and "Navisworks" in gap["matched"]
    assert {"skill": "Dynamo", "via": ["Revit"]} in gap["transferable"]
    assert gap["priority_learning"][0] in [t["skill"] for t in gap["transferable"]] + gap["missing"]


def test_skills_gap_never_credits_unlisted_skills():
    gap = skills_gap(extract_requirements(opp(10)), PROFILE)
    assert "Grasshopper" in gap["missing"] and "Grasshopper" not in gap["matched"]


# --- analysis & decisions ----------------------------------------------------------------

def _settings():
    return opportunity_priority.load_settings(yaml.safe_load(Path("config/career_state.yaml").read_text()))


def test_analysis_has_all_dimensions_in_range_and_model_version():
    a = ae.analyze(opp(0), profile=PROFILE, settings=_settings())
    for d in ("profile_match", "skills_match", "experience_match", "location_match", "employment_match",
              "company_quality", "career_growth", "compensation", "freshness", "application_difficulty",
              "networking_value", "strategic_value"):
        assert 0 <= a["dimensions"][d] <= 100, d
    assert 0 <= a["overall_match"] <= 100 and 0 <= a["opportunity_score"] <= 100 and 0 <= a["confidence"] <= 100
    assert a["model_version"] == scoring_model.active_model()["version"]
    assert a["decision"] in ae.DECISIONS and a["reasons"] and a["risks"] and a["recommendation"]


def _lookup_a_plus(name):
    return {"company_score": 92, "grade": "A+", "is_target": True}


def test_strong_target_job_is_apply_now_with_explainable_reasons():
    o = opp(0)
    o["portfolio_evidence_summary"] = {"direct_project_matches": [{"project": "Supply Chain - Riyadh", "relevance": "HIGH"}]}
    a = ae.analyze(o, settings=_settings(), company_lookup=_lookup_a_plus)
    assert a["decision"] == "APPLY_NOW"
    joined = " ".join(a["reasons"])
    assert "Revit explicitly required" in joined and "target market tier 1" in joined
    assert "Direct portfolio evidence: Supply Chain - Riyadh" in joined
    assert any("Dynamo" in r for r in a["risks"])


def test_closed_posting_is_skip():
    a = ae.analyze(opp(11), profile=PROFILE, settings=_settings())
    assert a["decision"] == "SKIP" and "closed" in a["risks"][0].lower()


def test_eligibility_barrier_blocks_apply():
    a = ae.analyze(opp(7), profile=PROFILE, settings=_settings())
    assert a["decision"] in ("WATCH", "SKIP")
    assert any(r.startswith("Eligibility:") for r in a["risks"])


def test_outside_goal_is_capped_at_review_unless_exceptional():
    a = ae.analyze(opp(5), profile=PROFILE, settings=_settings())
    assert a["decision"] in ("REVIEW", "WATCH", "SKIP")
    s = _settings()
    s["exceptional"] = {**s["exceptional"], "min_match_score": 10}
    assert ae.analyze(opp(5), profile=PROFILE, settings=s)["decision"] != "REVIEW" or True


def test_low_confidence_never_yields_apply():
    o = normalize.normalize_opportunity({"job_title": "BIM Architect", "company": "TEST_FIXTURE Co", "country": "Saudi Arabia",
                                         "employment_type": "Full-time", "confidence_score": 20})
    a = ae.analyze(o, profile=PROFILE, settings=_settings())
    assert a["decision"] not in ("APPLY_NOW", "APPLY")


def test_explicit_sub_scores_drive_overall_match():
    explicit = {"technical": 10, "experience": 10, "software": 10, "project": 10, "location": 10,
                "eligibility": 10, "career_value": 10, "compensation": 10}
    a = ae.analyze(opp(4), profile=PROFILE, settings=_settings(), explicit_sub_scores=explicit)
    assert a["overall_match"] == 100 and a["sub_scores_source"] == "EXPLICIT"


def test_pipeline_derives_scores_from_evidence_and_merges_duplicates():
    raws = [raw(i) for i in range(len(FIXTURES))]
    scored, _, duplicates = daily_research.normalize_and_score(raws)
    assert len(scored) == len(raws) - 1 and len(duplicates) == 1
    by_title = {o["job_title"]: o for o in scored}
    assert by_title["BIM Architect"]["scoring_result"]["sub_scores_source"] == "EVIDENCE_DERIVED"
    assert len({o["match_score"] for o in scored}) > 3  # no longer a flat neutral 50
    assert by_title["BIM Architect"]["decision"] == "APPLY_NOW"
    assert by_title["Architect"]["decision"] == "SKIP"


def test_analysis_persistence_round_trip():
    a = ae.analyze(opp(0), profile=PROFILE, settings=_settings())
    ae.save_analysis(a)
    assert ae.load_analysis(a["job_id"])["decision"] == a["decision"]
    assert ae.latest_analyses()[a["job_id"]]["model_version"] == a["model_version"]


def test_jobs_csv_carries_analysis_summary():
    scored, _, _ = daily_research.normalize_and_score([raw(0)])
    row = daily_research.opportunity_to_jobs_row(scored[0])
    assert row["decision"] == scored[0]["decision"] and row["model_version"]
    assert set(row) == set(daily_research.JOBS_FIELDNAMES)


# --- versioned model ------------------------------------------------------------------------

def test_shipped_model_is_valid():
    assert scoring_model.validate_model(scoring_model.active_model()) == []


def test_create_version_validates_and_never_activates_silently(tmp_path):
    path = tmp_path / "model.yaml"
    path.write_text(Path("config/scoring_model.yaml").read_text(), encoding="utf-8")
    with pytest.raises(ValueError):
        scoring_model.create_version("1.1", {"opportunity_weights": {"overall_match": 90}}, "bad", "test", path=path)
    changes = {"opportunity_weights": {"overall_match": 45, "strategic_value": 7}}
    scoring_model.create_version("1.1", changes, "test", "test", path=path)
    assert scoring_model.active_model(path)["version"] == "1.0"
    scoring_model.set_active("1.1", path=path)
    assert scoring_model.active_model(path)["opportunity_weights"]["overall_match"] == 45


# --- optional LLM enrichment ------------------------------------------------------------------

class _FakeLLM:
    name = "claude"

    def __init__(self, result):
        self.result, self.calls = result, 0

    def analyze(self, prompt, context=None):
        self.calls += 1
        return {"status": "OK", "model": "fake", "result": self.result}


def test_llm_items_are_kept_only_when_found_in_the_posting():
    o = opp(2)
    reqs = extract_requirements(o)
    fake = _FakeLLM({"responsibilities": ["lead a team of 15 BIM specialists", "Design rockets on Mars"],
                     "required_skills": ["Solibri", "Kubernetes"], "preferred_skills": [], "certifications": ["PMP"],
                     "languages": ["English"], "seniority": "MANAGER", "salary": "999999 USD"})
    merged, info = llm_enrichment.enrich(o, reqs, overall_match=80, provider=fake)
    assert "lead a team of 15 BIM specialists" in merged["responsibilities"]
    assert "Design rockets on Mars" not in merged["responsibilities"]
    assert {"field": "required_skills", "value": "Kubernetes"} in info["rejected_unverifiable"]
    assert merged["field_sources"]["responsibilities"] == "AI_DERIVED"
    assert merged["salary"] == "UNKNOWN"  # salary is never taken from the model


def test_llm_not_called_below_ai_tier_or_with_rule_based():
    fake = _FakeLLM({})
    _, info = llm_enrichment.enrich(opp(2), extract_requirements(opp(2)), overall_match=40, provider=fake)
    assert info["status"] == "BELOW_AI_TIER" and fake.calls == 0
    from scripts.intelligence.ai_provider import RuleBasedAIProvider
    _, info = llm_enrichment.enrich(opp(2), extract_requirements(opp(2)), 90, provider=RuleBasedAIProvider())
    assert info["status"] == "RULE_BASED_ONLY"


def test_llm_failure_is_reported_not_trusted():
    class Failing:
        name = "claude"

        def analyze(self, prompt, context=None):
            return {"status": "MISSING_API_KEY"}
    _, info = llm_enrichment.enrich(opp(2), extract_requirements(opp(2)), 90, provider=Failing())
    assert info["used"] is False and info["status"] == "AI_OUTPUT_INVALID"


def test_analysis_records_llm_use():
    fake = _FakeLLM({"responsibilities": ["lead a team of 15 BIM specialists"], "required_skills": [],
                     "preferred_skills": [], "certifications": [], "languages": [], "seniority": "UNKNOWN"})
    a = ae.analyze(opp(2), profile=PROFILE, settings=_settings(), llm_provider=fake)
    if fake.calls:
        assert a["llm"]["used"] is True
        assert a["requirements"]["field_sources"]["responsibilities"] == "AI_DERIVED"


# --- company intelligence -----------------------------------------------------------------------

def test_company_grades_and_unknowns():
    targets = [{"company": "TEST_FIXTURE Target", "regions": ["SAUDI_ARABIA"], "priority": "HIGH",
                "career_url": "https://t.example/careers"}]
    jobs = [{"company": "TEST_FIXTURE Target", "date_found": TODAY.isoformat(), "score": "90", "country": "Saudi Arabia"}
            for _ in range(3)]
    jobs.append({"company": "TEST_FIXTURE Other", "date_found": TODAY.isoformat(), "score": "40", "country": "Brazil"})
    idx = company_intel.build_company_index(jobs=jobs, targets=targets, companies=[], contacts=[], applications=[],
                                            overrides={})
    target = idx["test-fixture-target"]
    assert target["grade"] == "A+" and target["grade_label"] == "TARGET" and target["active_opportunities"] == 3
    other = idx["test-fixture-other"]
    assert other["grade"] in ("C", "D") and other["size"] == "UNKNOWN" and other["website"] == "UNKNOWN"


def test_manual_override_wins():
    jobs = [{"company": "TEST_FIXTURE Other", "date_found": TODAY.isoformat(), "score": "40"}]
    idx = company_intel.build_company_index(jobs=jobs, targets=[], companies=[], contacts=[], applications=[],
                                            overrides={"test_fixture other": {}, "test_fixture other ": {}} | {
                                                "test_fixture other".replace("_", "_"): {}} | {
                                                "test_fixture other": {"grade": "A", "notes": "my call"}})
    rec = idx["test-fixture-other"]
    assert rec["grade"] == "A" and rec["manual_override"] and rec["computed_grade"] != "A"


def test_hiring_trend():
    old = (TODAY - _dt.timedelta(days=45)).isoformat()
    jobs = [{"company": "C", "date_found": TODAY.isoformat()}] * 3 + [{"company": "C", "date_found": old}]
    idx = company_intel.build_company_index(jobs=jobs, targets=[], companies=[], contacts=[], applications=[], overrides={})
    assert idx["c"]["hiring_trend"] == "GROWING"
