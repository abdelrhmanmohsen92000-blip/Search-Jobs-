import pytest

from scripts.lib import scoring


def test_compute_weighted_score_perfect():
    sub_scores = {k: 10 for k in scoring.WEIGHTS}
    assert scoring.compute_weighted_score(sub_scores) == 100.0


def test_compute_weighted_score_zero():
    sub_scores = {k: 0 for k in scoring.WEIGHTS}
    assert scoring.compute_weighted_score(sub_scores) == 0.0


def test_compute_weighted_score_matches_weights():
    sub_scores = {k: 0 for k in scoring.WEIGHTS}
    sub_scores["technical"] = 10
    assert scoring.compute_weighted_score(sub_scores) == scoring.WEIGHTS["technical"]


def test_compute_weighted_score_missing_key_raises():
    sub_scores = {k: 5 for k in list(scoring.WEIGHTS)[:-1]}
    with pytest.raises(ValueError):
        scoring.compute_weighted_score(sub_scores)


def test_compute_weighted_score_out_of_range_raises():
    sub_scores = {k: 5 for k in scoring.WEIGHTS}
    sub_scores["technical"] = 11
    with pytest.raises(ValueError):
        scoring.compute_weighted_score(sub_scores)


@pytest.mark.parametrize("score,expected", [(95, "EXCEPTIONAL"), (80, "STRONG"), (65, "GOOD"), (45, "MODERATE"), (10, "LOW")])
def test_priority_bands(score, expected):
    assert scoring.priority_for_score(score) == expected


@pytest.mark.parametrize("score,expected", [(90, "APPLY_NOW"), (75, "APPLY"), (55, "CONSIDER"), (20, "WATCH")])
def test_recommendation_bands(score, expected):
    assert scoring.recommendation_for_score(score) == expected


def test_skill_gap_matches_and_misses():
    profile = {
        "skills": ["BIM Coordination", "Facade Design"],
        "software": [{"name": "Autodesk Revit"}],
    }
    matched, missing = scoring.skill_gap(
        ["BIM Coordination", "Structural Engineering"], ["Autodesk Revit", "Tekla Structures"], profile=profile
    )
    assert matched == ["BIM Coordination", "Autodesk Revit"]
    assert missing == ["Structural Engineering", "Tekla Structures"]


def test_skill_gap_is_case_insensitive():
    profile = {"skills": ["bim coordination"], "software": []}
    matched, missing = scoring.skill_gap(["BIM COORDINATION"], [], profile=profile)
    assert matched == ["BIM COORDINATION"]
    assert missing == []


def test_score_opportunity_record_full_shape():
    opportunity = {"skills_required": ["BIM Coordination"], "software_required": ["Autodesk Revit"], "source_url": "https://x"}
    sub_scores = {k: 8 for k in scoring.WEIGHTS}
    profile = {"skills": ["BIM Coordination"], "software": [{"name": "Autodesk Revit"}]}
    result = scoring.score_opportunity_record(opportunity, sub_scores, profile=profile)
    assert set(result) == {"score", "priority", "recommendation", "matched_skills", "missing_skills", "strengths", "risks"}
    assert result["score"] == 80.0
    assert result["missing_skills"] == []
