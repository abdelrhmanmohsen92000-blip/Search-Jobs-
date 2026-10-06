"""V1.3 Web Intelligence Layer tests."""
import json

from scripts.lib import entity_resolution, staleness
from scripts.lib.dedup import merge_duplicates
from scripts.web.base import PageExtractionResult, SearchProviderResult, SearchResult, WebSearchProvider
from scripts.web.manual_search_import import ManualSearchImportProvider, load_search_result_files, load_single_file
from scripts.web.opportunity_extractor import classify, extract_opportunity
from scripts.web.page_extractor import extract_from_html
from scripts.web.source_router import identify_source
from scripts.web.browser_queue import build_browser_queue
from scripts.web.search_engine import run_web_search
from scripts import web_research


# --- Search provider interface -------------------------------------------------

def test_search_result_from_dict_never_invents_fields():
    r = SearchResult.from_dict({"title": "X"})
    assert r.url is None
    assert r.snippet is None
    assert r.title == "X"


def test_web_search_provider_interface_requires_implementation():
    class Dummy(WebSearchProvider):
        pass
    import pytest
    with pytest.raises(NotImplementedError):
        Dummy().search("q")


def test_run_web_search_reports_unavailable_without_provider():
    results = run_web_search(["BIM Architect"], provider=None)
    assert len(results) == 1
    assert results[0].status == "SEARCH_PROVIDER_UNAVAILABLE"
    assert results[0].results == []  # never fabricates search results


# --- Manual search import -------------------------------------------------------

def test_manual_search_import_loads_valid_batch(tmp_path):
    f = tmp_path / "batch.json"
    f.write_text(json.dumps([{"title": "BIM Architect", "url": "https://x.com/1", "source": "Indeed"}]), encoding="utf-8")
    results, files_read, errors = load_search_result_files(tmp_path)
    assert len(results) == 1
    assert files_read == ["batch.json"]
    assert errors == []


def test_manual_search_import_reports_malformed_file_without_crashing(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not valid json", encoding="utf-8")
    results, files_read, errors = load_search_result_files(tmp_path)
    assert results == []
    assert errors and "bad.json" in errors[0]


def test_manual_search_import_empty_directory_reports_unavailable(tmp_path):
    provider = ManualSearchImportProvider(directory=tmp_path)
    result = provider.search()
    assert result.status == "UNAVAILABLE"
    assert result.results == []


def test_load_single_file_missing_file_reports_error():
    results, errors = load_single_file("/nonexistent/path/file.json")
    assert results == []
    assert "not found" in errors[0]


# --- Source routing / URL detection --------------------------------------------

def test_identify_known_sources():
    assert identify_source("https://www.linkedin.com/jobs/view/123")["source_name"] == "LinkedIn"
    assert identify_source("https://www.linkedin.com/jobs/view/123")["requires_browser"] is True
    assert identify_source("https://indeed.com/job/abc")["source_name"] == "Indeed"
    assert identify_source("https://indeed.com/job/abc")["requires_browser"] is False
    assert identify_source("https://remoteok.com/remote-jobs/1")["source_name"] == "Remote OK"


def test_identify_unknown_domain_never_assumed_known():
    result = identify_source("https://totally-random-blog.example/post/1")
    assert result["source_name"] == "Unknown"
    assert result["confidence"] == 0.0


def test_identify_company_careers_page_heuristic():
    result = identify_source("https://acme-architects.com/careers")
    assert result["source_name"] == "Company Career Page"
    assert 0 < result["confidence"] < 1.0


def test_identify_source_handles_missing_url():
    assert identify_source(None)["source_name"] == "Unknown"
    assert identify_source("")["confidence"] == 0.0


# --- HTML extraction -------------------------------------------------------------

def test_page_extractor_extracts_title_and_headings():
    html = "<html><head><title>Job Posting</title></head><body><h1>BIM Architect</h1><p>Full-time role in Berlin. Revit required.</p></body></html>"
    result = extract_from_html(html, url="https://example.com/job/1")
    assert result.status == "OK"
    assert result.title == "Job Posting"
    assert result.job_title == "BIM Architect"
    assert result.employment_type == "Full-time"
    assert "Revit" in result.skills


def test_page_extractor_detects_js_required():
    html = "<html><body><div id=\"root\"></div><script src=\"bundle.js\"></script></body></html>"
    result = extract_from_html(html, url="https://spa.example.com/job/1")
    assert result.status == "JS_REQUIRED"


def test_page_extractor_empty_html_is_parse_error():
    result = extract_from_html("", url="https://example.com")
    assert result.status == "PARSE_ERROR"


def test_page_extractor_never_fabricates_salary_when_absent():
    html = "<html><body><h1>BIM Coordinator</h1><p>Great opportunity, apply today.</p></body></html>"
    result = extract_from_html(html)
    assert result.salary is None


def test_page_extractor_extracts_links():
    html = '<html><body><a href="https://example.com/apply">Apply</a></body></html>'
    result = extract_from_html(html)
    assert result.application_url == "https://example.com/apply"


# --- Opportunity extraction / classification ------------------------------------

def test_classify_open_vacancy():
    assert classify("Senior BIM Architect — Dubai", "We are hiring, apply now, full-time role.") == "OPEN_VACANCY"


def test_classify_freelance_project():
    assert classify("Revit freelancer needed for villa project", "Short-term freelance gig, hourly rate.") == "FREELANCE_PROJECT"


def test_classify_company_signal():
    assert classify("Acme Architects wins major airport project", "The firm announces expansion of its BIM team.") == "COMPANY_SIGNAL"


def test_classify_irrelevant_news_article():
    assert classify("History of Modern Architecture", "An opinion piece exploring design styles over the decades.") == "IRRELEVANT"


def test_classify_empty_text_is_irrelevant():
    assert classify("", "") == "IRRELEVANT"


def test_extract_opportunity_returns_none_for_irrelevant():
    sr = SearchResult(title="History of Architecture", snippet="An opinion piece.", url="https://blog.example.com/1")
    candidate, label = extract_opportunity(sr)
    assert candidate is None
    assert label == "IRRELEVANT"


def test_extract_opportunity_populates_provenance_and_confidence():
    sr = SearchResult(title="BIM Coordinator - Berlin", snippet="Acme Studio is hiring a BIM Coordinator, apply now.",
                       url="https://indeed.com/job/1", source="Indeed", query="BIM Coordinator Germany", region="europe")
    candidate, label = extract_opportunity(sr)
    assert label == "OPEN_VACANCY"
    assert candidate["provenance"]["source_url"] == "https://indeed.com/job/1"
    assert candidate["provenance"]["search_query"] == "BIM Coordinator Germany"
    assert 0 <= candidate["confidence_score"] <= 100
    assert candidate["company"] == "Acme Studio"


def test_extract_opportunity_never_fabricates_company_when_unsupported():
    sr = SearchResult(title="BIM Architect - Dubai", snippet="Great role, apply now, full-time.", url="https://indeed.com/job/2")
    candidate, label = extract_opportunity(sr)
    assert label == "OPEN_VACANCY"
    assert candidate["company"] == ""  # nothing in the text supports a company guess


def test_extract_opportunity_uses_page_result_when_available():
    sr = SearchResult(title="BIM Architect", url="https://acme.com/careers/1")
    page = PageExtractionResult(status="OK", job_title="Senior BIM Architect", company="Acme Architects",
                                 employment_type="Full-time")
    candidate, label = extract_opportunity(sr, page)
    assert candidate["company"] == "Acme Architects"
    assert candidate["job_title"] == "Senior BIM Architect"
    assert candidate["provenance"]["extraction_method"] == "page_extraction"


# --- Web import pipeline (end-to-end, no real network) --------------------------

def test_web_research_process_results_routes_company_signal_to_hidden_pipeline():
    results = [SearchResult(title="Acme Group wins major airport expansion project",
                             snippet="Acme announces it is growing its BIM team.",
                             url="https://news.example.com/1", source="search_engine")]
    candidates, rejected, counts, hidden = web_research.process_search_results(results)
    assert candidates == []
    assert counts["COMPANY_SIGNAL"] == 1
    assert hidden and hidden[0]["company_name"] == "Acme Group"


def test_web_research_rejects_candidate_with_no_company_support():
    results = [SearchResult(title="BIM Architect - Dubai", snippet="Full-time role, apply now.", url="https://indeed.com/1")]
    candidates, rejected, counts, hidden = web_research.process_search_results(results)
    assert candidates == []
    assert len(rejected) == 1
    assert rejected[0]["rejection_reason"]


def test_web_research_extracts_scorable_candidate_when_company_supported():
    results = [SearchResult(title="BIM Architect - Berlin", snippet="Nordic Studio is hiring a BIM Architect, apply now.",
                             url="https://indeed.com/1", source="Indeed", region="europe")]
    candidates, rejected, counts, hidden = web_research.process_search_results(results)
    assert len(candidates) == 1
    assert candidates[0]["company"] == "Nordic Studio"


def test_web_import_dry_run_touches_nothing(monkeypatch, tmp_path):
    f = tmp_path / "batch.json"
    f.write_text(json.dumps([{"title": "X", "url": "https://x.com"}]), encoding="utf-8")
    result = web_research.run_web_import(directory=tmp_path, dry_run=True)
    assert result["dry_run"] is True
    assert result["search_results_loaded"] == 1


def test_web_import_no_fake_data_when_directory_empty(tmp_path):
    result = web_research.run_web_import(directory=tmp_path, dry_run=False)
    assert result["stats"]["search_results_loaded"] == 0
    assert result["scored"] == []


# --- Duplicate intelligence (source-preserving merge) ---------------------------

def test_merge_duplicates_preserves_alternate_sources():
    a = {"company": "Acme", "job_title": "BIM Architect", "city": "Dubai", "source": "Indeed", "source_url": "https://a.com/1"}
    b = {"company": "Acme", "job_title": "BIM Architect", "city": "Dubai", "source": "LinkedIn", "source_url": "https://b.com/1"}
    merged, dropped = merge_duplicates([a, b])
    assert len(merged) == 1
    assert dropped == 1
    assert merged[0]["alternate_sources"] == [{"source": "LinkedIn", "source_url": "https://b.com/1"}]


def test_merge_duplicates_keeps_distinct_opportunities_separate():
    a = {"company": "Acme", "job_title": "BIM Architect", "city": "Dubai", "source": "Indeed"}
    b = {"company": "Beta", "job_title": "Interior Designer", "city": "London", "source": "Bayt"}
    merged, dropped = merge_duplicates([a, b])
    assert len(merged) == 2
    assert dropped == 0


# --- Company entity resolution ---------------------------------------------------

def test_entity_resolution_merges_known_variants():
    mapping = entity_resolution.resolve_companies(["Al Futtaim", "Al-Futtaim", "Al Futtaim Group"])
    canonicals = set(mapping.values())
    assert len(canonicals) == 1


def test_entity_resolution_never_merges_different_companies():
    mapping = entity_resolution.resolve_companies(["Al Futtaim", "Al Futtan"])
    assert mapping["Al Futtaim"] != mapping["Al Futtan"]


def test_entity_resolution_canonical_key_strips_suffixes():
    assert entity_resolution.canonical_key("Acme Group") == entity_resolution.canonical_key("Acme")


def test_resolve_company_against_known_pool():
    known = ["Al Futtaim Group"]
    assert entity_resolution.resolve_company("Al-Futtaim", known) == "Al Futtaim Group"
    assert entity_resolution.resolve_company("Totally Different Co", known) == "Totally Different Co"


# --- Stale opportunity detection -------------------------------------------------

def test_staleness_new_for_recent_posting():
    import datetime as _dt
    opp = {"date_posted": _dt.date.today().isoformat()}
    assert staleness.compute_lifecycle_status(opp) == "NEW"


def test_staleness_stale_for_old_posting():
    import datetime as _dt
    old_date = (_dt.date.today() - _dt.timedelta(days=60)).isoformat()
    opp = {"date_posted": old_date}
    assert staleness.compute_lifecycle_status(opp) == "STALE"


def test_staleness_uncertain_without_any_date():
    assert staleness.compute_lifecycle_status({}) == "UNCERTAIN"


def test_staleness_closed_only_with_explicit_evidence():
    import datetime as _dt
    opp = {"date_posted": _dt.date.today().isoformat(), "description": "This position has been filled."}
    assert staleness.compute_lifecycle_status(opp) == "CLOSED"


def test_staleness_never_closed_from_age_alone():
    import datetime as _dt
    very_old = (_dt.date.today() - _dt.timedelta(days=400)).isoformat()
    opp = {"date_posted": very_old}
    assert staleness.compute_lifecycle_status(opp) == "STALE"  # not CLOSED — no evidence of closure


# --- Browser queue ----------------------------------------------------------------

def test_browser_queue_includes_browser_required_sources_despite_disabled_flag():
    tasks = build_browser_queue(region="gulf", limit_per_source=2)
    sources = {t["source"] for t in tasks}
    assert "LinkedIn Jobs" in sources  # enabled: false in config, but must still appear here


def test_browser_queue_tasks_have_required_fields():
    tasks = build_browser_queue(region="europe", limit_per_source=1)
    for t in tasks:
        assert set(t) == {"source", "query", "region", "priority", "expected_value", "manual_action"}
        assert t["priority"] in ("HIGH", "MEDIUM", "LOW")


def test_browser_queue_sorted_by_priority():
    tasks = build_browser_queue(region="gulf", limit_per_source=3)
    priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ranks = [priority_rank[t["priority"]] for t in tasks]
    assert ranks == sorted(ranks)


# --- No-fake-data policy -----------------------------------------------------------

def test_source_provider_result_to_dict_never_adds_fake_results():
    r = SearchProviderResult(provider="x", status="UNAVAILABLE", error="blocked")
    assert r.to_dict()["results"] == []


def test_page_extraction_js_required_has_no_fabricated_fields():
    html = "<html><body>" + "please enable javascript" + "</body></html>"
    result = extract_from_html(html)
    assert result.status == "JS_REQUIRED"
    assert result.company is None
    assert result.salary is None
