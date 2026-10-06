"""Phase 4 — Real Job Acquisition & Live Career Intelligence.

Covers the genuinely new pieces this phase added on top of the existing
Phase 3 architecture: canonical error-type classification, source-health
routing priority, company career-page priority, and per-opportunity
portfolio-evidence integration in the research pipeline. No test depends on
live network access — everything here uses local fixtures/mocks, consistent
with the rest of this suite.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.error_types import ERROR_TYPES, classify_error
from scripts.lib import source_health as health_lib
from scripts.sources import company_careers as company_careers_lib
from scripts.sources.base import SourceRunResult
from scripts.daily_research import normalize_and_score


# --- error classification --------------------------------------------------

def test_classify_timeout():
    assert classify_error("UNAVAILABLE", "TimeoutError: timed out") == "TIMEOUT"


def test_classify_http_403():
    assert classify_error("UNAVAILABLE", "URLError: Tunnel connection failed: 403 Forbidden") in ("HTTP_403", "NETWORK_ERROR")
    assert classify_error("UNAVAILABLE", "HTTP 403: Forbidden") == "HTTP_403"


def test_classify_http_401():
    assert classify_error("UNAVAILABLE", "HTTP 401: Unauthorized") == "HTTP_401"


def test_classify_rate_limited():
    assert classify_error("UNAVAILABLE", "HTTP 429: Too Many Requests") == "RATE_LIMITED"
    assert classify_error("UNAVAILABLE", "rate limit exceeded") == "RATE_LIMITED"


def test_classify_auth_required():
    assert classify_error("UNAVAILABLE", "authentication required: no API key configured") == "AUTH_REQUIRED"


def test_classify_browser_required():
    assert classify_error("BROWSER_REQUIRED", None) == "BROWSER_REQUIRED"


def test_classify_no_results():
    assert classify_error("EMPTY", None) == "NO_RESULTS"


def test_classify_search_provider_unavailable():
    assert classify_error("SEARCH_PROVIDER_UNAVAILABLE", "no provider configured") == "SEARCH_PROVIDER_UNAVAILABLE"


def test_classify_parser_error():
    assert classify_error("ERROR", "JSONDecodeError: Expecting value") == "PARSER_ERROR"


def test_classify_malformed_response():
    assert classify_error("ERROR", "malformed response from provider") == "INVALID_RESPONSE"


def test_classify_network_error():
    assert classify_error("UNAVAILABLE", "URLError: Connection refused") == "NETWORK_ERROR"


def test_classify_unrecognized_error_falls_back_to_provider_error():
    assert classify_error("ERROR", "something totally unexpected happened") == "PROVIDER_ERROR"


def test_classify_success_is_not_an_error():
    assert classify_error("SUCCESS", None) is None


def test_every_canonical_type_is_a_string():
    assert all(isinstance(t, str) for t in ERROR_TYPES)


# --- source health priority routing -----------------------------------------

def test_healthy_source_gets_high_priority():
    row = {"status": "AVAILABLE", "consecutive_failures": "0"}
    assert health_lib.source_priority(row) == "HIGH"


def test_repeatedly_blocked_source_drops_to_low():
    row = {"status": "BLOCKED", "consecutive_failures": "6"}
    assert health_lib.source_priority(row) == "LOW"


def test_single_failure_does_not_permanently_disable_a_source():
    row = {"status": "UNAVAILABLE", "consecutive_failures": "1"}
    assert health_lib.source_priority(row) == "MEDIUM"


def test_auth_required_source_is_disabled_until_credentials_exist():
    row = {"status": "UNAVAILABLE", "error_type": "AUTH_REQUIRED", "consecutive_failures": "1"}
    assert health_lib.source_priority(row) == "DISABLED"


def test_browser_required_manual_source_routes_medium_not_disabled():
    row = {"status": "MANUAL", "consecutive_failures": "0"}
    assert health_lib.source_priority(row) == "MEDIUM"


def test_record_result_populates_canonical_error_type_and_detail():
    row = health_lib.record_result("Test Board", "UNAVAILABLE", error="HTTP 403: Forbidden", existing=None)
    assert row["error_type"] == "HTTP_403"
    assert row["error_detail"] == "HTTP 403: Forbidden"
    assert row["consecutive_failures"] == 1


def test_record_result_resets_consecutive_failures_on_success():
    failed = health_lib.record_result("Test Board", "UNAVAILABLE", error="HTTP 403: Forbidden", existing=None)
    recovered = health_lib.record_result("Test Board", "SUCCESS", error=None, existing=failed)
    assert recovered["consecutive_failures"] == 0
    assert recovered["status"] == "AVAILABLE"


# --- company career page priority -------------------------------------------

def test_add_company_source_records_region_and_priority(tmp_path, monkeypatch):
    csv_path = tmp_path / "company_career_pages.csv"
    row = company_careers_lib.add_company_source(
        "Acme Architects", "https://acme.example/careers",
        source_type="architecture_firm", region="UAE", priority="HIGH", csv_path=csv_path,
    )
    assert row["region"] == "UAE"
    assert row["priority"] == "HIGH"
    stored = company_careers_lib.load_company_sources(csv_path)
    assert stored[0]["priority"] == "HIGH"


def test_run_configured_company_sources_checks_high_priority_first_when_limited(tmp_path, monkeypatch):
    csv_path = tmp_path / "company_career_pages.csv"
    company_careers_lib.add_company_source("Low Co", "https://low.example/careers", priority="LOW", csv_path=csv_path)
    company_careers_lib.add_company_source("High Co", "https://high.example/careers", priority="HIGH", csv_path=csv_path)

    def fake_fetch(self, query=None, limit=None):
        return SourceRunResult(source=f"careers:{query['company_name']}", status="FETCHED_UNPARSED", raw_count=10)

    monkeypatch.setattr(company_careers_lib.CompanyCareersAdapter, "fetch", fake_fetch)
    results = company_careers_lib.run_configured_company_sources(csv_path=csv_path, limit=1)
    assert len(results) == 1
    assert results[0].source == "careers:High Co"


# --- never fabricate live jobs when a provider fails ------------------------

def test_no_results_never_becomes_a_fake_opportunity():
    result = SourceRunResult(source="Test Board", status="EMPTY")
    assert result.opportunities == []
    assert result.status == "EMPTY"


def test_blocked_provider_never_returns_fabricated_opportunities():
    result = SourceRunResult(source="Test Board", status="UNAVAILABLE", error="URLError: Tunnel connection failed: 403 Forbidden")
    assert result.opportunities == []
    assert classify_error(result.status, result.error) in ("HTTP_403", "NETWORK_ERROR")


# --- portfolio evidence integrated into the research pipeline --------------

def _profile_with_real_data():
    import yaml
    profile = yaml.safe_load(Path("config/profile_skills.yaml").read_text())
    portfolio = yaml.safe_load(Path("config/portfolio_projects.yaml").read_text())
    profile["portfolio_projects"] = portfolio["portfolio_projects"]
    return profile


def test_normalize_and_score_attaches_portfolio_evidence_summary():
    profile = _profile_with_real_data()
    raw = [{
        "source": "Manual Import # TEST_FIXTURE",
        "job_title": "BIM Coordinator",
        "company": "TEST_FIXTURE Co",
        "country": "Saudi Arabia",
        "project_types": ["Healthcare"],
        "software_required": ["Autodesk Revit"],
        "skills_required": ["BIM Coordination"],
    }]
    scored, rejected, duplicates = normalize_and_score(raw, profile=profile)
    assert not rejected
    assert len(scored) == 1
    summary = scored[0]["portfolio_evidence_summary"]
    assert summary != "PORTFOLIO_DATA_INSUFFICIENT"
    assert any(m["project"] == "Supply Chain - Riyadh" for m in summary["direct_project_matches"])
    assert any(m["capability"] == "Autodesk Revit" for m in summary["profile_capability_matches"])
    assert any(m["region"] == "Saudi Arabia" for m in summary["regional_matches"])


def test_normalize_and_score_reports_insufficient_when_truly_no_evidence():
    profile = _profile_with_real_data()
    raw = [{
        "source": "Manual Import # TEST_FIXTURE",
        "job_title": "Marine Engineer",
        "company": "TEST_FIXTURE Shipyard",
        "country": "Brazil",
        "project_types": ["Marine Engineering"],
        "software_required": ["SolidWorks"],
    }]
    scored, _, _ = normalize_and_score(raw, profile=profile)
    assert scored[0]["portfolio_evidence_summary"] == "PORTFOLIO_DATA_INSUFFICIENT"


def test_normalize_and_score_never_cites_unrelated_project_for_villa_job():
    profile = _profile_with_real_data()
    raw = [{
        "source": "Manual Import # TEST_FIXTURE",
        "job_title": "Luxury Villa Interior Designer",
        "company": "TEST_FIXTURE Studio",
        "country": "Egypt",
        "project_types": ["Luxury Villas", "Residential"],
        "skills_required": ["Interior Design"],
    }]
    scored, _, _ = normalize_and_score(raw, profile=profile)
    summary = scored[0]["portfolio_evidence_summary"]
    project_names = {m["project"] for m in summary["direct_project_matches"]}
    assert "Supply Chain - Riyadh" not in project_names
