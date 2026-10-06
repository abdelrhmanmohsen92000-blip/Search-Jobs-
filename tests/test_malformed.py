from scripts.lib import dedup, normalize
from scripts.daily_research import normalize_and_score


def test_normalize_opportunity_tolerates_wrong_types_gracefully():
    raw = {"company": "Acme", "job_title": "BIM Architect", "skills_required": 12345}
    opp = normalize.normalize_opportunity(raw)
    assert opp["skills_required"] == []  # unrecognized type -> safe empty default, never crashes


def test_normalize_opportunity_tolerates_non_string_remote():
    raw = {"company": "Acme", "job_title": "BIM Architect", "remote": 1}
    opp = normalize.normalize_opportunity(raw)
    assert opp["remote"] is None  # ambiguous, not silently coerced to True


def test_dedup_handles_completely_empty_records():
    a = {}
    b = {}
    unique, duplicates = dedup.deduplicate([a, b])
    # two fully-empty records normalize to the same key and are deduplicated
    assert len(unique) == 1
    assert len(duplicates) == 1


def test_normalize_and_score_pipeline_flags_invalid_record_without_crashing():
    raw_records = [{"job_title": "BIM Architect"}]  # missing company -> schema invalid
    scored, duplicates = normalize_and_score(raw_records)
    assert len(scored) == 1
    assert any("VALIDATION_ERROR" in flag for flag in scored[0]["risk_flags"])
    # still gets a score even though flagged, so the pipeline never hard-fails on bad input
    assert scored[0]["match_score"] is not None


def test_normalize_and_score_handles_empty_batch():
    scored, duplicates = normalize_and_score([])
    assert scored == []
    assert duplicates == []
