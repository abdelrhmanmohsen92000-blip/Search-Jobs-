import pytest

from scripts.lib import normalize, scoring


def test_normalize_empty_dict_produces_empty_required_fields():
    opp = normalize.normalize_opportunity({})
    assert opp["company"] == ""
    assert opp["job_title"] == ""
    # id is still generated deterministically even from empty inputs
    assert opp["id"]


def test_validate_catches_empty_company_and_title():
    opp = normalize.normalize_opportunity({})
    opp.pop("_sub_scores", None)
    errors = normalize.validate_opportunity(opp)
    assert any("non-empty" in e for e in errors)


def test_skill_gap_handles_missing_requirement_lists():
    matched, missing = scoring.skill_gap(None, None, profile={"skills": [], "software": []})
    assert matched == []
    assert missing == []


def test_skill_gap_handles_missing_profile_sections():
    matched, missing = scoring.skill_gap(["Revit"], ["AutoCAD"], profile={})
    assert matched == []
    assert set(missing) == {"Revit", "AutoCAD"}


def test_compute_weighted_score_rejects_missing_criteria_cleanly():
    with pytest.raises(ValueError, match="Missing sub-scores"):
        scoring.compute_weighted_score({})


def test_normalize_handles_none_values_in_optional_fields():
    raw = {"company": "Acme", "job_title": "BIM Architect", "salary_min": None, "country": None}
    opp = normalize.normalize_opportunity(raw)
    assert opp["salary_min"] is None
    assert opp["region"] == "unclassified"
