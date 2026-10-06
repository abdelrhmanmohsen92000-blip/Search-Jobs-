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


def test_normalize_and_score_pipeline_rejects_invalid_record_without_crashing():
    raw_records = [{"job_title": "BIM Architect"}]  # missing company -> rejected, not scored
    scored, rejected, duplicates = normalize_and_score(raw_records)
    assert scored == []
    assert len(rejected) == 1
    assert rejected[0]["rejection_reason"]  # reason recorded, record never silently discarded


def test_normalize_and_score_scores_valid_record_with_validation_warning():
    # company/title present but something else is off -> still scored, just flagged
    raw_records = [{"company": "Acme", "job_title": "BIM Architect", "employment_type": "Bogus-Type"}]
    scored, rejected, duplicates = normalize_and_score(raw_records)
    assert rejected == []
    assert len(scored) == 1
    assert any("VALIDATION_ERROR" in flag for flag in scored[0]["risk_flags"])
    assert scored[0]["match_score"] is not None


def test_normalize_and_score_handles_empty_batch():
    scored, rejected, duplicates = normalize_and_score([])
    assert scored == []
    assert rejected == []
    assert duplicates == []
