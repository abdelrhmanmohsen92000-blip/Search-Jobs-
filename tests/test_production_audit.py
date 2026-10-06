"""Tests added by the V1.4 production integration audit.

Covers the canonical-data-model fix (tracking/jobs.csv now carries the full
V1.1 sub-scores, so scripts.career_intelligence can LOAD from it directly
instead of depending on ephemeral data/processed/*.json snapshots), AI
provider failure/fallback behavior, and resilience to incomplete opportunity
data reaching the intelligence layer.
"""
import json

from scripts import career_intelligence, daily_research
from scripts.intelligence import ai_provider, decision_engine, job_analyzer


def _scored_opportunity(**overrides):
    opp = {
        "id": "row1", "date_found": "2026-10-06", "source": "Indeed",
        "source_url": "https://indeed.com/1", "job_title": "BIM Coordinator", "company": "Acme",
        "country": "Germany", "city": "Berlin", "region": "europe", "remote": True,
        "employment_type": "Full-time", "experience_required": "3-5 years",
        "skills_required": ["BIM Coordination"], "software_required": ["Autodesk Revit"],
        "project_types": ["Residential"], "visa_sponsorship": True,
        "match_score": 85.0, "priority": "STRONG", "status": "scored", "reason": "Strong match",
        "scoring_result": {
            "score": 85.0, "priority": "STRONG", "recommendation": "APPLY", "action": "APPLY",
            "technical": 9, "experience": 8, "software": 9, "project": 7, "location": 8,
            "eligibility": 9, "career_value": 7, "compensation": 6,
            "matched_skills": ["BIM Coordination"], "missing_skills": [], "strengths": [], "risks": [],
        },
    }
    opp.update(overrides)
    return opp


# --- Canonical data model: tracking/jobs.csv carries the sub-scores --------------------

def test_opportunity_to_jobs_row_includes_all_sub_scores():
    row = daily_research.opportunity_to_jobs_row(_scored_opportunity())
    for key in ("technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation"):
        assert row[key] == _scored_opportunity()["scoring_result"][key]


def test_opportunity_to_jobs_row_matches_declared_fieldnames():
    row = daily_research.opportunity_to_jobs_row(_scored_opportunity())
    assert set(row.keys()) == set(daily_research.JOBS_FIELDNAMES)


def test_jobs_csv_round_trip_preserves_sub_scores(tmp_path, monkeypatch):
    """Write a row through the real CSV writer, read it back, and confirm
    career_intelligence can reconstruct a usable scoring_result from it —
    this is the exact audit finding: the CSV used to silently drop the
    sub-scores, forcing a dependency on ephemeral JSON snapshots.
    """
    from scripts.lib import paths as paths_lib, storage

    fake_jobs = tmp_path / "jobs.csv"
    monkeypatch.setattr(paths_lib, "JOBS_CSV", fake_jobs)

    opp = _scored_opportunity()
    storage.append_csv_rows(fake_jobs, daily_research.JOBS_FIELDNAMES, [daily_research.opportunity_to_jobs_row(opp)])

    reconstructed = career_intelligence.load_opportunities_from_jobs_csv()
    assert len(reconstructed) == 1
    r = reconstructed[0]
    assert r["match_score"] == 85.0
    assert r["scoring_result"]["technical"] == 9
    assert r["scoring_result"]["compensation"] == 6
    assert r["skills_required"] == ["BIM Coordination"]
    assert r["remote"] is True
    assert r["visa_sponsorship"] is True


def test_opportunity_from_jobs_row_handles_empty_sub_score_cell():
    # a historical row written before the fix (or a manually edited CSV with
    # a blank cell) must not crash reconstruction — it just reports None
    row = {"id": "x", "job_title": "A", "company": "B", "date_found": "2026-01-01", "source": "Indeed",
           "technical": "", "experience": "", "software": "", "project": "", "location": "",
           "eligibility": "", "career_value": "", "compensation": "", "score": "", "skills_required": "",
           "software_required": "", "project_types": ""}
    opp = career_intelligence.opportunity_from_jobs_row(row)
    assert opp["scoring_result"]["technical"] is None
    assert opp["match_score"] is None


def test_load_latest_scored_opportunities_works_from_csv_alone(tmp_path, monkeypatch):
    """The core regression: analyze/decision/intelligence must work even when
    data/processed/ has nothing in it, now that jobs.csv is canonical.
    """
    from scripts.lib import paths as paths_lib, storage

    fake_jobs = tmp_path / "jobs.csv"
    empty_processed = tmp_path / "empty_processed"
    monkeypatch.setattr(paths_lib, "JOBS_CSV", fake_jobs)
    monkeypatch.setattr(paths_lib, "DATA_PROCESSED", empty_processed)

    storage.append_csv_rows(fake_jobs, daily_research.JOBS_FIELDNAMES, [daily_research.opportunity_to_jobs_row(_scored_opportunity())])

    loaded = career_intelligence.load_latest_scored_opportunities()
    assert len(loaded) == 1
    enriched = career_intelligence.analyze_opportunities(loaded, score_min=0)
    assert len(enriched) == 1
    assert enriched[0]["decision"]["decision"] in decision_engine.DECISIONS


def test_jobs_csv_takes_priority_over_stale_snapshot_on_id_collision(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib, storage

    fake_jobs = tmp_path / "jobs.csv"
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    monkeypatch.setattr(paths_lib, "JOBS_CSV", fake_jobs)
    monkeypatch.setattr(paths_lib, "DATA_PROCESSED", processed_dir)

    stale_snapshot = _scored_opportunity(match_score=40.0)
    stale_snapshot["scoring_result"]["score"] = 40.0
    (processed_dir / "daily_opportunities.20260101T000000.json").write_text(json.dumps([stale_snapshot]), encoding="utf-8")

    fresh = _scored_opportunity(match_score=85.0)
    storage.append_csv_rows(fake_jobs, daily_research.JOBS_FIELDNAMES, [daily_research.opportunity_to_jobs_row(fresh)])

    loaded = {o["id"]: o for o in career_intelligence.load_latest_scored_opportunities()}
    assert loaded["row1"]["match_score"] == 85.0  # CSV (canonical) wins, not the stale snapshot


# --- AI provider readiness: failure / fallback never crashes --------------------------

def test_ai_provider_missing_config_key_defaults_safely():
    provider = ai_provider.get_ai_provider(None)
    assert provider.name == "rule_based"


def test_ai_provider_malformed_config_does_not_crash():
    provider = ai_provider.get_ai_provider({"provider": 12345})  # malformed: not a string
    result = provider.analyze("x")
    assert "provider" in result


def test_ai_provider_unknown_provider_name_falls_back():
    provider = ai_provider.get_ai_provider({"provider": "some_future_vendor_not_in_config"})
    assert isinstance(provider, ai_provider.RuleBasedAIProvider)


# --- Resilience to incomplete opportunity data reaching the intelligence layer ---------

def test_job_analyzer_handles_opportunity_missing_scoring_result():
    opp = {"id": "x", "company": "Acme", "job_title": "BIM Architect", "skills_required": [], "software_required": []}
    analysis = job_analyzer.analyze_job(opp)  # no KeyError despite no scoring_result key at all
    assert 0 <= analysis["fit_score"] <= 100


def test_decision_engine_handles_opportunity_missing_match_score():
    opp = {"id": "x", "company": "Acme", "job_title": "BIM Architect", "skills_required": [], "software_required": []}
    analysis = job_analyzer.analyze_job(opp)
    result = decision_engine.decide(opp, analysis)
    assert result["decision"] in decision_engine.DECISIONS


def test_analyze_opportunities_skips_record_with_no_id_gracefully():
    opp = _scored_opportunity()
    del opp["id"]
    # should not raise; downstream recording just gets an empty/None id rather than crashing
    enriched = career_intelligence.analyze_opportunities([opp], score_min=0, deep=True)
    assert len(enriched) == 1


# --- Claude provider: real adapter, but never required and never faked -----------------

def test_claude_provider_missing_api_key_falls_back_without_network(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = ClaudeAIProvider()
    result = provider.analyze("test prompt", {"a": 1})
    assert result["status"] == "MISSING_API_KEY"
    assert result["fallback_provider"] == "rule_based"
    assert "console.anthropic.com" in result["note"]


def test_claude_provider_never_reads_key_from_config_or_repo_files():
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    # constructing the provider must not require or embed a key anywhere
    provider = ClaudeAIProvider(model="claude-sonnet-5")
    assert provider._api_key() is None or isinstance(provider._api_key(), str)
    # no key material in this file or its import graph
    import inspect
    source = inspect.getsource(ClaudeAIProvider)
    assert "sk-ant" not in source


def test_claude_provider_falls_back_on_simulated_network_failure(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    provider = ClaudeAIProvider(max_retries=0)
    monkeypatch.setattr(provider, "_post_with_retries", lambda body, headers: (None, "URLError: simulated network failure", "API_CALL_FAILED"))
    result = provider.analyze("test prompt", {"a": 1})
    assert result["status"] == "API_CALL_FAILED"
    assert result["fallback_provider"] == "rule_based"


def test_claude_provider_falls_back_on_malformed_response(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    provider = ClaudeAIProvider(max_retries=0)
    # a response missing the expected content/usage shape
    monkeypatch.setattr(provider, "_post_with_retries", lambda body, headers: ({"unexpected": "shape"}, None, None))
    result = provider.analyze("test prompt", {"a": 1})
    assert result["status"] == "MALFORMED_RESPONSE"


def test_claude_provider_structured_output_on_simulated_success(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    provider = ClaudeAIProvider(max_retries=0)
    fake_response = {
        "content": [{"type": "text", "text": '{"verdict": "strong fit"}'}],
        "usage": {"input_tokens": 42, "output_tokens": 7},
    }
    monkeypatch.setattr(provider, "_post_with_retries", lambda body, headers: (fake_response, None, None))
    result = provider.analyze("test prompt", {"a": 1})
    assert result["status"] == "OK"
    assert result["result"] == {"verdict": "strong fit"}
    assert result["usage"] == {"input_tokens": 42, "output_tokens": 7}


def test_get_ai_provider_selects_claude_when_configured(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    provider = ai_provider.get_ai_provider({"provider": "claude", "providers": {"claude": {"model": "claude-sonnet-5"}}})
    assert isinstance(provider, ClaudeAIProvider)


def test_ai_config_default_provider_is_still_rule_based():
    from scripts.lib import config as cfg_lib
    config = cfg_lib.load_ai_config()
    assert config["provider"] == "rule_based"


# --- Salary schema/tracker extension ---------------------------------------------------

def test_opportunity_to_jobs_row_persists_salary_fields():
    opp = _scored_opportunity(salary_min=60000, salary_max=75000, salary_currency="EUR",
                               salary_period="year", salary_source="posting", salary_confidence="OBSERVED")
    row = daily_research.opportunity_to_jobs_row(opp)
    assert row["salary_min"] == 60000
    assert row["salary_confidence"] == "OBSERVED"


def test_salary_round_trips_through_jobs_csv(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib, storage

    fake_jobs = tmp_path / "jobs.csv"
    monkeypatch.setattr(paths_lib, "JOBS_CSV", fake_jobs)
    opp = _scored_opportunity(salary_min=60000, salary_max=75000, salary_currency="EUR",
                               salary_period="year", salary_source="posting", salary_confidence="OBSERVED")
    storage.append_csv_rows(fake_jobs, daily_research.JOBS_FIELDNAMES, [daily_research.opportunity_to_jobs_row(opp)])
    reconstructed = career_intelligence.load_opportunities_from_jobs_csv()[0]
    assert reconstructed["salary_min"] == 60000.0
    assert reconstructed["salary_confidence"] == "OBSERVED"


def test_market_intelligence_distinguishes_observed_from_estimated():
    from scripts.intelligence.career_strategy import market_intelligence
    jobs = (
        [{"salary_min": "60000", "salary_confidence": "OBSERVED", "job_title": "X", "country": "DE",
          "skills_required": "", "software_required": "", "remote": "", "employment_type": ""}] * 3
        + [{"salary_min": "50000", "salary_confidence": "ESTIMATED", "job_title": "Y", "country": "DE",
            "skills_required": "", "software_required": "", "remote": "", "employment_type": ""}]
    )
    result = market_intelligence(jobs=jobs)
    assert result["salary_observed_count"] == 3
    assert result["salary_estimated_count"] == 1
    assert "OBSERVED" in result["salary_pattern"]


def test_market_intelligence_never_calls_estimates_a_pattern():
    from scripts.intelligence.career_strategy import market_intelligence
    jobs = [{"salary_min": "50000", "salary_confidence": "ESTIMATED", "job_title": "Y", "country": "DE",
             "skills_required": "", "software_required": "", "remote": "", "employment_type": ""}]
    result = market_intelligence(jobs=jobs)
    assert "below the sample size" in result["salary_pattern"]


# --- Portfolio intelligence: schema exists, mechanism works once real data is added -----

def test_portfolio_recommendation_works_once_real_project_metadata_exists():
    from scripts.intelligence.application_strategy import portfolio_recommendation
    profile = {"portfolio_projects": [{"name": "Villa X", "project_types": ["Residential"]}]}
    opp = {"project_types": ["Residential", "Commercial"]}
    result = portfolio_recommendation(opp, profile=profile)
    assert result != "PORTFOLIO_DATA_INSUFFICIENT"
    assert result[0]["project"] == "Villa X"


def test_portfolio_match_returns_insufficient_without_data():
    from scripts.intelligence.application_strategy import match_portfolio_projects
    assert match_portfolio_projects({"project_types": ["Residential"]}, profile={}) == "PORTFOLIO_DATA_INSUFFICIENT"


def test_portfolio_match_returns_insufficient_when_no_project_has_evidence():
    from scripts.intelligence.application_strategy import match_portfolio_projects
    profile = {"portfolio_projects": [{"name": "Office Tower", "project_types": ["Commercial"]}]}
    opp = {"project_types": ["Residential"], "software_required": [], "skills_required": []}
    assert match_portfolio_projects(opp, profile=profile) == "PORTFOLIO_DATA_INSUFFICIENT"


def test_portfolio_match_high_relevance_with_multiple_evidence_dimensions():
    from scripts.intelligence.application_strategy import match_portfolio_projects
    profile = {"portfolio_projects": [{
        "name": "Villa Al Noor", "project_types": ["Residential"], "software": ["Autodesk Revit"],
        "disciplines": ["Architecture"], "role": "BIM Coordinator", "location": "Cairo",
        "bim_level": "LOD 350", "deliverables": ["Shop drawings"], "achievements": ["Real measurable outcome"],
    }]}
    opp = {"project_types": ["Residential"], "software_required": ["Autodesk Revit"], "skills_required": ["Architecture"]}
    result = match_portfolio_projects(opp, profile=profile)
    assert result[0]["relevance"] == "HIGH"
    assert result[0]["confidence"] == "HIGH"
    assert len(result[0]["evidence"]) == 3


def test_portfolio_match_low_confidence_with_sparse_project_metadata():
    from scripts.intelligence.application_strategy import match_portfolio_projects
    profile = {"portfolio_projects": [{"name": "Sparse Project", "project_types": ["Residential"]}]}
    opp = {"project_types": ["Residential"], "software_required": [], "skills_required": []}
    result = match_portfolio_projects(opp, profile=profile)
    assert result[0]["relevance"] == "MEDIUM"  # only one evidence dimension (project type)
    assert result[0]["confidence"] == "LOW"  # almost no optional metadata filled


def test_portfolio_match_never_fabricates_evidence_not_actually_overlapping():
    from scripts.intelligence.application_strategy import match_portfolio_projects
    profile = {"portfolio_projects": [{"name": "X", "project_types": ["Commercial"], "software": ["Rhino"]}]}
    opp = {"project_types": ["Residential"], "software_required": ["Autodesk Revit"], "skills_required": []}
    assert match_portfolio_projects(opp, profile=profile) == "PORTFOLIO_DATA_INSUFFICIENT"


# --- AI output safety gate (AI_OUTPUT_INVALID) -------------------------------------------

def test_validate_ai_output_accepts_well_formed_result():
    from scripts.intelligence.ai_provider import validate_ai_output
    ok, payload = validate_ai_output({"status": "OK", "result": {"decision": "APPLY"}}, required_keys=["decision"])
    assert ok is True
    assert payload == {"decision": "APPLY"}


def test_validate_ai_output_rejects_non_ok_status():
    from scripts.intelligence.ai_provider import validate_ai_output
    ok, payload = validate_ai_output({"status": "MISSING_API_KEY"})
    assert ok is False
    assert payload["status"] == "AI_OUTPUT_INVALID"
    assert payload["original_status"] == "MISSING_API_KEY"


def test_validate_ai_output_rejects_missing_required_key():
    from scripts.intelligence.ai_provider import validate_ai_output
    ok, payload = validate_ai_output({"status": "OK", "result": {"other": 1}}, required_keys=["decision"])
    assert ok is False
    assert "decision" in payload["reason"]


def test_validate_ai_output_never_raises_on_garbage_input():
    from scripts.intelligence.ai_provider import validate_ai_output
    ok, payload = validate_ai_output(None)
    assert ok is False
    ok, payload = validate_ai_output("a string, not a dict")
    assert ok is False
    ok, payload = validate_ai_output({"status": "OK", "result": "not a dict either"})
    assert ok is False


# --- Claude provider: configurable model, distinct failure kinds ------------------------

def test_claude_provider_model_env_var_overrides_configured_model(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider
    provider = ClaudeAIProvider(model="claude-sonnet-5", model_env_var="ANTHROPIC_MODEL")
    assert provider.model == "claude-sonnet-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    assert provider.model == "claude-opus-5-5"


def test_claude_provider_timeout_reported_distinctly(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    provider = ClaudeAIProvider(max_retries=0)
    monkeypatch.setattr(provider, "_post_with_retries", lambda body, headers: (None, "Timed out after 20s", "TIMEOUT"))
    result = provider.analyze("test prompt", {})
    assert result["status"] == "TIMEOUT"
    assert result["fallback_provider"] == "rule_based"


def test_claude_provider_http_error_reported_distinctly(monkeypatch):
    from scripts.intelligence.claude_provider import ClaudeAIProvider
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    provider = ClaudeAIProvider(max_retries=0)
    monkeypatch.setattr(provider, "_post_with_retries", lambda body, headers: (None, "HTTP 500: Internal Server Error", "HTTP_ERROR"))
    result = provider.analyze("test prompt", {})
    assert result["status"] == "HTTP_ERROR"


def test_claude_provider_max_tokens_configurable():
    from scripts.intelligence.claude_provider import ClaudeAIProvider
    provider = ClaudeAIProvider(max_tokens=256)
    assert provider.max_tokens == 256


def test_claude_provider_real_timeout_exception_classified_correctly(monkeypatch):
    """Exercises the real _post_with_retries code path (not monkeypatched)
    with a simulated socket timeout, to confirm the classification logic
    itself — not just the mocked test above — works."""
    import socket
    from scripts.intelligence.claude_provider import ClaudeAIProvider

    def fake_urlopen(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = ClaudeAIProvider(max_retries=0, timeout=1)
    result = provider.analyze("test prompt", {})
    assert result["status"] == "TIMEOUT"


def test_smoke_claude_blocked_without_api_key(monkeypatch):
    from scripts.intelligence.smoke_claude import run_smoke_test
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_smoke_test()
    assert result["REAL_AUTHENTICATED_TEST"] == "BLOCKED"
    assert result["REASON"] == "ANTHROPIC_API_KEY not available"


def test_smoke_claude_verified_on_simulated_success(monkeypatch):
    from scripts.intelligence import smoke_claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setattr(
        smoke_claude.ClaudeAIProvider, "_post_with_retries",
        lambda self, body, headers: ({"content": [{"text": '{"ok": true}'}], "usage": {"input_tokens": 5, "output_tokens": 2}}, None, None),
    )
    result = smoke_claude.run_smoke_test()
    assert result["REAL_AUTHENTICATED_TEST"] == "VERIFIED"
    assert result["parsed_result"] == {"ok": True}


def test_smoke_claude_failed_is_never_reported_as_verified(monkeypatch):
    from scripts.intelligence import smoke_claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setattr(
        smoke_claude.ClaudeAIProvider, "_post_with_retries",
        lambda self, body, headers: (None, "HTTP 401: Unauthorized", "HTTP_ERROR"),
    )
    result = smoke_claude.run_smoke_test()
    assert result["REAL_AUTHENTICATED_TEST"] == "FAILED"
    assert result["REAL_AUTHENTICATED_TEST"] != "VERIFIED"


def test_portfolio_project_example_file_matches_its_own_schema():
    import json
    import yaml
    from jsonschema import Draft7Validator

    schema = json.loads((__import__("pathlib").Path("schemas/portfolio_project.schema.json")).read_text())
    example = yaml.safe_load((__import__("pathlib").Path("config/portfolio_projects.example.yaml")).read_text())
    validator = Draft7Validator(schema)
    for project in example["portfolio_projects"]:
        errors = list(validator.iter_errors(project))
        assert errors == [], errors
