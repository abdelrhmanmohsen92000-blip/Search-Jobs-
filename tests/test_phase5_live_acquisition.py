"""Phase 5 — Live Opportunity Acquisition & Source Expansion.

Every HTTP call is mocked at the adapter boundary (no network in the suite),
every company/job is a synthetic TEST_FIXTURE, every write goes to tmp_path.
Live behaviour against real hosts is verified separately (see
docs/PRODUCTION_READINESS.md, Phase 5) and never required for these tests.
"""
import csv
import datetime as _dt
import json
import re
import urllib.error
from pathlib import Path

import pytest

from scripts import daily_research, research
from scripts.lib import dedup, normalize, opportunity_modes, source_health, source_registry, staleness
from scripts.lib import config as cfg_lib
from scripts.search_config import build_search_engine_queries
from scripts.sources import base as sources_base, company_careers
from scripts.web import brave_search, jobposting_parser, search_discovery
from scripts.web.base import SearchProviderResult, SearchResult

TODAY = _dt.date.today().isoformat()


def jobposting_html(title="TEST_FIXTURE BIM Architect", company="TEST_FIXTURE Studio", city="Riyadh", country="SA",
                    employment="FULL_TIME", posted=TODAY, valid=None, extra=None, body="", links=()):
    posting = {"@context": "https://schema.org", "@type": "JobPosting", "title": title,
               "hiringOrganization": {"@type": "Organization", "name": company},
               "jobLocation": {"@type": "Place", "address": {"addressLocality": city, "addressCountry": country}},
               "employmentType": employment, "datePosted": posted, "description": "<p>Revit, LOD 350.</p>"}
    if valid:
        posting["validThrough"] = valid
    posting.update(extra or {})
    posting = {k: v for k, v in posting.items() if v is not None}
    anchors = "".join(f'<a href="{l}">job</a>' for l in links)
    return (f'<html><head><script type="application/ld+json">{json.dumps(posting)}</script></head>'
            f"<body>{body}{anchors}</body></html>")


# --- source registry ---------------------------------------------------------

def test_registry_reflects_real_implementation():
    by_name = {s["name"]: s for s in source_registry.list_sources(environ={})}
    assert by_name["Remote OK"]["implementation"] == "ADAPTER"
    assert by_name["Official company career pages"]["implementation"] == "CAREER_PAGES"
    assert by_name["LinkedIn Jobs"]["implementation"] == "BROWSER_QUEUE"
    assert by_name["Brave Search API"]["implementation"] == "SEARCH_PROVIDER"
    for name in ("SerpAPI", "Bing Web Search API", "Tavily"):
        assert by_name[name]["implementation"] == "NOT_IMPLEMENTED"
    assert by_name["Indeed"]["implementation"] == "RAW_FETCH_ONLY"


def test_capabilities_default_false_and_are_never_overstated():
    by_name = {s["name"]: s for s in source_registry.list_sources(environ={})}
    assert by_name["Remote OK"]["capabilities"]["employment_type"] is False
    assert by_name["Remote OK"]["capabilities"]["keyword_filter"] is False
    assert by_name["Remotive"]["capabilities"]["keyword_filter"] is True
    assert by_name["Remotive"]["capabilities"]["employment_type"] is False
    assert not any(by_name["Bayt"]["capabilities"].values())


def test_missing_credentials_mean_auth_required_not_no_jobs():
    src = {"name": "Brave Search API", "credential_env": "BRAVE_SEARCH_API_KEY", "implemented": True}
    assert source_registry.unattempted_status(src, environ={}) == "AUTH_REQUIRED"
    assert source_registry.unattempted_status(src, environ={"BRAVE_SEARCH_API_KEY": "x"}) == "NOT_RUN_THIS_CYCLE"
    assert source_registry.unattempted_status({"name": "SerpAPI", "implemented": False}) == "NOT_IMPLEMENTED"
    assert source_registry.unattempted_status({"name": "X", "enabled": False}) == "DISABLED"


# --- HTTP: bounded retry, no hammering ---------------------------------------

class _FakeUrlopen:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise self.exc


def _http_error(code):
    return urllib.error.HTTPError("https://example.test", code, "x", {}, None)


@pytest.mark.parametrize("code", [403, 401, 429, 404])
def test_refusals_are_never_retried(monkeypatch, code):
    fake = _FakeUrlopen(_http_error(code))
    monkeypatch.setattr(sources_base.urllib.request, "urlopen", fake)
    monkeypatch.setattr(sources_base.time, "sleep", lambda s: None)
    _, error, status = sources_base.http_fetch("https://example.test", retries=3)
    assert fake.calls == 1 and status == code and error


def test_proxy_refused_tunnel_is_not_retried(monkeypatch):
    fake = _FakeUrlopen(urllib.error.URLError("Tunnel connection failed: 403 Forbidden"))
    monkeypatch.setattr(sources_base.urllib.request, "urlopen", fake)
    monkeypatch.setattr(sources_base.time, "sleep", lambda s: None)
    sources_base.http_fetch("https://example.test", retries=3)
    assert fake.calls == 1


def test_server_errors_retry_with_a_bound(monkeypatch):
    fake = _FakeUrlopen(_http_error(503))
    monkeypatch.setattr(sources_base.urllib.request, "urlopen", fake)
    monkeypatch.setattr(sources_base.time, "sleep", lambda s: None)
    sources_base.http_fetch("https://example.test", retries=2)
    assert fake.calls == 3


def test_remotive_stops_after_a_refusal(monkeypatch):
    from scripts.sources.remotive import RemotiveAdapter
    calls = []
    monkeypatch.setattr("scripts.sources.remotive.http_get_json",
                        lambda url, **k: (calls.append(url), (None, "URLError: Tunnel connection failed: 403 Forbidden"))[1])
    result = RemotiveAdapter().fetch(search_terms=["a", "b", "c"])
    assert len(calls) == 1 and result.status == "UNAVAILABLE"


# --- source health: states, cooldown, recovery -------------------------------

NOW = "2026-01-10T12:00:00"


def _rec(raw, error=None, existing=None, **kw):
    return source_health.record_result("TEST_FIXTURE src", raw, error, existing, now=NOW, **kw)


def test_success_is_verified_without_cooldown():
    row = _rec("SUCCESS", result_count=4)
    assert row["health_state"] == "VERIFIED" and row["cooldown_until"] == "" and row["last_result_count"] == 4


def test_403_is_blocked_with_long_cooldown():
    row = _rec("UNAVAILABLE", "HTTP 403: Forbidden", http_status=403)
    assert row["health_state"] == "BLOCKED" and row["http_status"] == 403
    assert row["cooldown_until"] == "2026-01-11T12:00:00"


def test_429_is_rate_limited_with_short_cooldown():
    row = _rec("UNAVAILABLE", "HTTP 429: Too Many Requests", http_status=429)
    assert row["health_state"] == "RATE_LIMITED" and row["cooldown_until"] == "2026-01-10T13:00:00"


def test_timeouts_back_off_exponentially_but_are_capped():
    first = _rec("UNAVAILABLE", "TimeoutError: timed out")
    second = _rec("UNAVAILABLE", "TimeoutError: timed out", existing=first)
    assert first["health_state"] == "UNAVAILABLE"
    assert first["cooldown_until"] == "2026-01-10T12:15:00"
    assert second["cooldown_until"] == "2026-01-10T12:30:00"
    assert source_health.cooldown_minutes("UNAVAILABLE", 50) == source_health.load_policy()["max_cooldown_minutes"]


def test_parser_failure_state():
    assert _rec("PARSE_ERROR", "PARSER_ERROR: JSON-LD present but unreadable")["health_state"] == "PARSER_FAILED"


def test_recovery_clears_cooldown_and_failures():
    failed = _rec("UNAVAILABLE", "HTTP 403: Forbidden")
    recovered = _rec("SUCCESS", existing=failed)
    assert recovered["health_state"] == "VERIFIED"
    assert recovered["consecutive_failures"] == 0 and recovered["cooldown_until"] == ""


def test_cooldown_is_a_window_not_a_permanent_ban():
    row = _rec("UNAVAILABLE", "HTTP 403: Forbidden")
    assert source_health.in_cooldown(row, _dt.datetime(2026, 1, 10, 18))
    assert not source_health.in_cooldown(row, _dt.datetime(2026, 1, 11, 12, 1))


def test_cooldown_skip_leaves_the_last_real_outcome(tmp_path):
    path = tmp_path / "source_health.csv"
    source_health.update_source_health([{"source": "S", "status": "UNAVAILABLE", "error": "HTTP 403: Forbidden"}], path)
    before = source_health.load_health(path)["S"]
    source_health.update_source_health([{"source": "S", "status": "COOLDOWN"}], path)
    after = source_health.load_health(path)["S"]
    assert after["health_state"] == "BLOCKED" and after["request_count"] == before["request_count"]


def test_auth_required_is_recorded_without_counting_a_request(tmp_path):
    path = tmp_path / "source_health.csv"
    source_health.update_source_health([{"source": "Brave Search API", "status": "AUTH_REQUIRED",
                                         "error": "BRAVE_SEARCH_API_KEY is not set"}], path)
    row = source_health.load_health(path)["Brave Search API"]
    assert row["health_state"] == "AUTH_REQUIRED" and row["request_count"] == ""


def test_pre_phase_5_health_rows_still_load(tmp_path):
    path = tmp_path / "source_health.csv"
    path.write_text("source,status,last_success,last_failure,error_type,request_count,success_count,updated_at\n"
                    "Old,AVAILABLE,2026-01-01,,,3,3,2026-01-01\n", encoding="utf-8")
    row = source_health.load_health(path)["Old"]
    assert not source_health.in_cooldown(row)
    source_health.update_source_health([{"source": "Old", "status": "SUCCESS"}], path)
    assert source_health.load_health(path)["Old"]["health_state"] == "VERIFIED"


# --- JobPosting extraction / job verification ---------------------------------

def test_jobposting_fields_are_extracted_not_inferred():
    page = jobposting_parser.parse_job_page(jobposting_html(), "https://careers.example.test/jobs/1", "TEST_FIXTURE")
    opp = page.opportunities[0]
    assert page.status == "PARSED"
    assert (opp["job_title"], opp["company"], opp["city"], opp["country"]) == \
        ("TEST_FIXTURE BIM Architect", "TEST_FIXTURE Studio", "Riyadh", "Saudi Arabia")
    assert opp["employment_type"] == "Full-time"
    assert opp["remote"] is None  # not stated -> unknown, never False
    assert opp["application_url"] == "UNKNOWN"
    assert opp["provenance"]["extraction_method"] == "json_ld_jobposting"


def test_direct_apply_sets_application_url():
    html = jobposting_html(extra={"directApply": True, "url": "https://careers.example.test/jobs/7"})
    opp = jobposting_parser.parse_job_page(html, "https://careers.example.test/x", "s").opportunities[0]
    assert opp["application_url"] == "https://careers.example.test/jobs/7"


def test_missing_employment_type_and_date_stay_unknown():
    html = jobposting_html(employment=None, posted=None)
    opp = jobposting_parser.parse_job_page(html, "u", "s").opportunities[0]
    assert opp["employment_type"] is None and opp["date_posted"] is None
    assert staleness.compute_freshness(opp) == "UNKNOWN"
    assert opportunity_modes.classify_modes(opp)[0] == []


def test_page_without_structured_data_creates_no_opportunity():
    page = jobposting_parser.parse_job_page("<html><body>BIM Architect wanted! Apply now.</body></html>", "u", "s")
    assert page.status == "NO_STRUCTURED_DATA" and page.opportunities == []


def test_unreadable_json_ld_is_parser_failed():
    page = jobposting_parser.parse_job_page('<script type="application/ld+json">{nope</script>', "u", "s")
    assert page.status == "PARSER_FAILED"


def test_closed_page_and_expired_posting_are_closed():
    closed_text = jobposting_parser.parse_job_page(jobposting_html(body="This job is no longer available."), "u", "s")
    expired = jobposting_parser.parse_job_page(jobposting_html(valid="2020-01-01"), "u", "s")
    for page in (closed_text, expired):
        raw = page.opportunities[0]
        assert staleness.compute_lifecycle_status(raw) == "CLOSED"
        assert staleness.compute_freshness(raw) == "CLOSED"


def test_jobposting_in_graph_and_lists():
    data = {"@graph": [{"@type": "Organization"}, {"@type": ["JobPosting"], "title": "A"}]}
    html = f'<script type="application/ld+json">{json.dumps([data, {"@type": "JobPosting", "title": "B"}])}</script>'
    titles = [o["job_title"] for o in jobposting_parser.parse_job_page(html, "u", "s").opportunities]
    assert titles == ["A", "B"]


def test_job_links_stay_on_the_same_site():
    html = ('<a href="/careers/job/1">a</a><a href="https://jobs.example.test/positions/2">b</a>'
            '<a href="https://other.test/jobs/3">c</a><a href="/about">d</a><a href="mailto:x@y">e</a>')
    links = jobposting_parser.extract_job_links(html, "https://www.example.test/careers", limit=10)
    assert links == ["https://www.example.test/careers/job/1", "https://jobs.example.test/positions/2"]


# --- freshness ------------------------------------------------------------------

@pytest.mark.parametrize("days,label", [(0, "FRESH"), (3, "FRESH"), (10, "RECENT"), (25, "AGING"), (45, "STALE")])
def test_freshness_buckets(days, label):
    now = _dt.datetime(2026, 3, 1)
    posted = (now - _dt.timedelta(days=days)).date().isoformat()
    assert staleness.compute_freshness({"date_posted": posted}, now=now) == label


def test_freshness_never_uses_date_found():
    assert staleness.compute_freshness({"date_found": TODAY}) == "UNKNOWN"


# --- company career pages ---------------------------------------------------------

def test_real_registry_never_enables_an_unverified_url():
    targets = company_careers.load_targets()
    assert targets
    for t in targets:
        if t.get("enabled"):
            assert company_careers.has_verified_url(t), t["company"]
            assert t["url_verification"]["status"] in ("SEARCH_INDEXED", "LIVE_VERIFIED")
        if t["career_url"] == "UNKNOWN":
            assert t["enabled"] is False


def test_target_rows_exclude_unknown_urls():
    targets = [{"company": "A", "career_url": "https://a.example.test/careers",
                "url_verification": {"status": "SEARCH_INDEXED"}, "regions": ["UAE"]},
               {"company": "B", "career_url": "UNKNOWN", "url_verification": {"status": "UNVERIFIED"}},
               {"company": "C", "career_url": "https://c.example.test", "url_verification": {"status": "GUESSED"}}]
    assert [r["company"] for r in company_careers.target_rows(targets)] == ["A"]
    assert [t["company"] for t in company_careers.unverified_targets(targets)] == ["B", "C"]


def _fake_site(pages, calls=None):
    def fetch(url, **kwargs):
        if calls is not None:
            calls.append(url)
        if url in pages:
            return pages[url].encode("utf-8"), None, 200
        return None, "HTTP 404: Not Found", 404
    return fetch


def test_careers_adapter_follows_job_links_and_parses(monkeypatch):
    site = {"https://co.example.test/careers": jobposting_html(title="TEST_FIXTURE Listing", links=(
        "/careers/job/1", "/careers/job/2")).replace("JobPosting", "WebPage"),
            "https://co.example.test/careers/job/1": jobposting_html(title="TEST_FIXTURE BIM Coordinator"),
            "https://co.example.test/careers/job/2": jobposting_html(title="TEST_FIXTURE Revit Architect")}
    monkeypatch.setattr(company_careers, "http_fetch", _fake_site(site))
    result = company_careers.CompanyCareersAdapter().fetch(
        {"company_name": "TEST_FIXTURE Co", "careers_page": "https://co.example.test/careers", "max_requests": 5})
    assert result.status == "SUCCESS" and result.requests_made == 3
    assert {o["job_title"] for o in result.opportunities} == {"TEST_FIXTURE BIM Coordinator", "TEST_FIXTURE Revit Architect"}
    assert all(o["company_career_url"] == "https://co.example.test/careers" for o in result.opportunities)
    assert all(o["source"] == "careers:TEST_FIXTURE Co" for o in result.opportunities)


def test_careers_adapter_respects_request_budget(monkeypatch):
    links = tuple(f"/careers/job/{i}" for i in range(20))
    site = {"https://co.example.test/careers": "<html>" + "".join(f'<a href="{l}">x</a>' for l in links) + "</html>"}
    calls = []
    monkeypatch.setattr(company_careers, "http_fetch", _fake_site(site, calls))
    company_careers.CompanyCareersAdapter().fetch(
        {"company_name": "C", "careers_page": "https://co.example.test/careers", "max_requests": 4})
    assert len(calls) == 4


def test_careers_page_without_jobposting_is_fetched_unparsed(monkeypatch):
    monkeypatch.setattr(company_careers, "http_fetch",
                        _fake_site({"https://co.example.test/careers": "<html>Join us!</html>"}))
    result = company_careers.CompanyCareersAdapter().fetch(
        {"company_name": "C", "careers_page": "https://co.example.test/careers"})
    assert result.status == "FETCHED_UNPARSED" and result.opportunities == []


def test_careers_page_blocked_reports_status_code(monkeypatch):
    monkeypatch.setattr(company_careers, "http_fetch", lambda url, **k: (None, "HTTP 403: Forbidden", 403))
    result = company_careers.CompanyCareersAdapter().fetch(
        {"company_name": "C", "careers_page": "https://co.example.test/careers"})
    assert result.status == "UNAVAILABLE" and result.http_status == 403


def test_company_pages_in_cooldown_are_not_requested(tmp_path, monkeypatch):
    csv_path = tmp_path / "pages.csv"
    company_careers.add_company_source("Cool Co", "https://cool.example.test/careers", csv_path=csv_path)
    calls = []
    monkeypatch.setattr(company_careers, "http_fetch", _fake_site({}, calls))
    health = {"careers:Cool Co": {"cooldown_until": "2999-01-01T00:00:00"}}
    results = company_careers.run_configured_company_sources(csv_path=csv_path, health=health)
    assert calls == [] and [r.status for r in results] == ["COOLDOWN"]


# --- search engine provider & discovery ----------------------------------------

def test_brave_without_key_makes_no_request():
    calls = []
    provider = brave_search.BraveSearchProvider(api_key="", fetcher=lambda *a, **k: calls.append(a))
    result = provider.search('"BIM Architect" Riyadh')
    assert result.status == "AUTH_REQUIRED" and calls == []


def test_brave_reads_key_only_from_environment(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    assert brave_search.BraveSearchProvider().configured is False
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-not-a-real-key")
    assert brave_search.BraveSearchProvider().configured is True


def test_brave_parses_documented_shape_and_drops_bad_urls():
    body = json.dumps({"web": {"results": [
        {"title": "<b>BIM Architect</b>", "url": "https://jobs.example.test/1", "description": "Riyadh"},
        {"title": "bad", "url": "javascript:alert(1)"}]}}).encode()
    sent = {}

    def fetcher(url, **kwargs):
        sent.update(url=url, headers=kwargs["headers"])
        return body, None, 200
    result = brave_search.BraveSearchProvider(api_key="k", fetcher=fetcher).search('"BIM Architect" Riyadh', limit=5)
    assert result.status == "LIVE" and [r.url for r in result.results] == ["https://jobs.example.test/1"]
    assert result.results[0].title == "BIM Architect"
    assert sent["headers"]["X-Subscription-Token"] == "k" and "count=5" in sent["url"]


@pytest.mark.parametrize("status,error,expected", [
    (401, "HTTP 401: Unauthorized", "AUTH_REQUIRED"), (429, "HTTP 429: Too Many", "RATE_LIMITED"),
    (403, "HTTP 403: Forbidden", "BLOCKED"), (None, "URLError: Tunnel connection failed: 403 Forbidden", "BLOCKED"),
    (503, "HTTP 503: Unavailable", "UNAVAILABLE"), (None, "TimeoutError: timed out", "UNAVAILABLE")])
def test_brave_failures_are_classified(status, error, expected):
    provider = brave_search.BraveSearchProvider(api_key="k", fetcher=lambda *a, **k: (None, error, status))
    assert provider.search("q").status == expected


def test_brave_malformed_response_is_parser_failed():
    provider = brave_search.BraveSearchProvider(api_key="k", fetcher=lambda *a, **k: (b"<html>", None, 200))
    assert provider.search("q").status == "PARSER_FAILED"


class _StubProvider:
    name = "TEST_FIXTURE search"
    configured = True

    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def search(self, query, limit=10):
        self.calls += 1
        return self.responses.pop(0) if self.responses else SearchProviderResult(provider=self.name, status="EMPTY")


def _sr(url):
    return SearchResult(title="TEST_FIXTURE lead", url=url, snippet="Great BIM job in Riyadh", source="stub")


def test_search_snippets_alone_never_become_opportunities():
    provider = _StubProvider([SearchProviderResult(provider="s", status="LIVE", results=[_sr("https://x.example.test/a")])])
    outcome = search_discovery.run_search_discovery(
        provider, ["q"], fetcher=_fake_site({"https://x.example.test/a": "<html>Great BIM job in Riyadh</html>"}))
    assert outcome["opportunities"] == [] and outcome["stats"]["unverified_leads"] == 1


def test_search_lead_with_jobposting_page_becomes_verified_opportunity():
    provider = _StubProvider([SearchProviderResult(provider="s", status="LIVE",
                                                   results=[_sr("https://x.example.test/a?utm_source=s"),
                                                            _sr("https://x.example.test/a")])])
    outcome = search_discovery.run_search_discovery(
        provider, [{"query_string": '"BIM Architect" Riyadh'}],
        fetcher=_fake_site({"https://x.example.test/a?utm_source=s": jobposting_html()}))
    assert len(outcome["opportunities"]) == 1  # the tracking-param duplicate is fetched once
    assert outcome["opportunities"][0]["provenance"]["search_query"] == '"BIM Architect" Riyadh'


def test_discovery_skips_protected_hosts_and_stops_on_auth_required():
    provider = _StubProvider([
        SearchProviderResult(provider="s", status="LIVE", results=[_sr("https://www.linkedin.com/jobs/view/1")]),
        SearchProviderResult(provider="s", status="AUTH_REQUIRED", error="401")])
    calls = []
    outcome = search_discovery.run_search_discovery(provider, ["q1", "q2", "q3"], fetcher=_fake_site({}, calls))
    assert calls == [] and outcome["stats"]["protected_skipped"] == 1
    assert outcome["status"] == "AUTH_REQUIRED" and provider.calls == 2


def test_discovery_page_fetch_budget():
    results = [_sr(f"https://x.example.test/{i}") for i in range(10)]
    calls = []
    search_discovery.run_search_discovery(
        _StubProvider([SearchProviderResult(provider="s", status="LIVE", results=results)]), ["q"],
        max_page_fetches=3, fetcher=_fake_site({}, calls))
    assert len(calls) == 3


# --- regional search & role matrix ----------------------------------------------

def test_query_budget_follows_regional_tiers():
    queries = build_search_engine_queries(limit=32)
    counts = {}
    for q in queries:
        counts[q["region"]] = counts.get(q["region"], 0) + 1
    assert counts["SAUDI_ARABIA"] > counts["UAE"] > counts["QATAR"] > counts["EGYPT"]
    assert counts["GLOBAL"] >= 1 and len(queries) <= 32


def test_core_roles_lead_each_region_and_one_role_per_query():
    queries = build_search_engine_queries(limit=32)
    saudi = [q for q in queries if q["region"] == "SAUDI_ARABIA"]
    core = (cfg_lib.load_search_matrix()["role_query_matrix"]["core"])
    tiers = [q["role_tier"] for q in saudi]
    assert saudi[0]["role"] == "BIM Architect"
    assert tiers[:len(core)] == ["core"] * len(core)  # every core role before any secondary/adjacent one
    assert tiers == sorted(tiers, key=["core", "secondary", "adjacent"].index)
    assert all(q["query_string"].count('"') == 2 and " AND " not in q["query_string"] for q in queries)


def test_mode_query_terms():
    remote = build_search_engine_queries({"name": "REMOTE_FULL_TIME", "remote_only_locations": True}, limit=3)
    freelance = build_search_engine_queries({"name": "FREELANCE", "query_terms": ["freelance", "project"]}, limit=6)
    assert all(q["query_string"].endswith(" remote") for q in remote)
    assert all(q["query_string"].endswith((" freelance", " project")) for q in freelance)
    plain = build_search_engine_queries({"name": "FULL_TIME", "query_terms": []}, limit=4)
    assert not any(q["query_string"].endswith(("freelance", "project", "contract")) for q in plain)


# --- dedup -------------------------------------------------------------------------

def test_tracking_parameters_do_not_change_identity():
    a = dedup.make_id("Co", "BIM Architect", "Riyadh", "https://www.Example.test/jobs/1/?utm_source=x&gclid=1#top")
    b = dedup.make_id("Co", "BIM Architect", "Riyadh", "https://example.test/jobs/1")
    assert a == b
    assert dedup.make_id("Co", "BIM Architect", "Riyadh", "https://example.test/jobs/1?id=2") != b


def test_company_page_and_board_copy_merge_with_provenance():
    raws = [
        {"source": "careers:TEST_FIXTURE Co", "source_url": "https://co.example.test/careers/job/1",
         "job_title": "TEST_FIXTURE BIM Architect", "company": "TEST_FIXTURE Co", "city": "Riyadh",
         "employment_type": "Full-time"},
        {"source": "TEST_FIXTURE board", "source_url": "https://board.example.test/j/99?utm_campaign=x",
         "job_title": "TEST_FIXTURE BIM Architect", "company": "TEST_FIXTURE Co", "city": "Riyadh"},
    ]
    scored, _, duplicates = daily_research.normalize_and_score(raws, profile={})
    assert len(scored) == 1 and len(duplicates) == 1
    assert scored[0]["alternate_sources"][0]["source"] == "TEST_FIXTURE board"


def test_unknown_application_url_is_filled_by_later_evidence(tmp_path):
    jobs = tmp_path / "jobs.csv"
    base = {"source": "s", "source_url": "https://co.example.test/j/1", "job_title": "TEST_FIXTURE Role",
            "company": "TEST_FIXTURE Co", "city": "Doha"}
    first, _, _ = daily_research.normalize_and_score([base], profile={})
    later, _, _ = daily_research.normalize_and_score(
        [{**base, "application_url": "https://co.example.test/apply/1"}], profile={})
    daily_research.upsert_jobs_rows([daily_research.opportunity_to_jobs_row(first[0])], jobs)
    daily_research.upsert_jobs_rows([daily_research.opportunity_to_jobs_row(later[0])], jobs)
    rows = list(csv.DictReader(jobs.open(encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["application_url"] == "https://co.example.test/apply/1"


# --- mode integration from structured data ------------------------------------------

@pytest.mark.parametrize("employment,extra,expected", [
    ("FULL_TIME", None, ["FULL_TIME"]),
    ("FULL_TIME", {"jobLocationType": "TELECOMMUTE"}, ["REMOTE_FULL_TIME", "FULL_TIME"]),
    ("PART_TIME", None, ["PART_TIME"]),
    ("CONTRACTOR", None, ["CONTRACT"]),
    ("INTERN", None, []),
])
def test_structured_employment_type_drives_modes(employment, extra, expected):
    raw = jobposting_parser.parse_job_page(jobposting_html(employment=employment, extra=extra), "u", "s").opportunities[0]
    opp = normalize.normalize_opportunity(raw)
    assert opportunity_modes.classify_modes(opp)[0] == expected


def test_freelance_is_never_inferred_from_a_jobposting_without_evidence():
    raw = jobposting_parser.parse_job_page(jobposting_html(employment=None), "u", "s").opportunities[0]
    assert "FREELANCE" not in opportunity_modes.classify_modes(normalize.normalize_opportunity(raw))[0]


# --- full pipeline: dry run, live run, persistence, browser queue, AI -------------

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from scripts.lib import paths as p
    jobs = tmp_path / "jobs.csv"
    jobs.write_text("id\n", encoding="utf-8")
    (tmp_path / "networking.csv").write_text("person\n", encoding="utf-8")
    for attr, value in {"JOBS_CSV": jobs, "SOURCE_HEALTH_CSV": tmp_path / "source_health.csv",
                        "DATA_DIR": tmp_path / "data", "DATA_PROCESSED": tmp_path / "data" / "processed",
                        "DATA_ARCHIVE": tmp_path / "data" / "archive", "REPORTS_DIR": tmp_path / "reports",
                        "NETWORKING_CSV": tmp_path / "networking.csv", "DATA_RESEARCH_RUNS": tmp_path / "runs",
                        "COMPANY_CAREER_PAGES_CSV": tmp_path / "pages.csv",
                        "CAREER_MODE_RUNS": tmp_path / "mode_runs.json"}.items():
        monkeypatch.setattr(p, attr, value)
    targets = tmp_path / "targets.yaml"
    targets.write_text(
        "companies:\n  - company: TEST_FIXTURE Co\n    regions: [SAUDI_ARABIA]\n"
        "    career_url: https://co.example.test/careers\n    url_verification: {status: SEARCH_INDEXED}\n"
        "    priority: HIGH\n    enabled: true\n", encoding="utf-8")
    monkeypatch.setattr(company_careers, "TARGET_COMPANIES", targets)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", lambda *a, **k: (None, "HTTP 403: Forbidden"))
    monkeypatch.setattr("scripts.sources.remotive.http_get_json", lambda *a, **k: (None, "HTTP 403: Forbidden"))
    site = {"https://co.example.test/careers": '<a href="/careers/job/1">x</a>',
            "https://co.example.test/careers/job/1": jobposting_html(company="TEST_FIXTURE Co")}
    monkeypatch.setattr(company_careers, "http_fetch", _fake_site(site))
    return tmp_path


def test_dry_run_makes_no_request_and_writes_nothing(isolated, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not make a request")
    monkeypatch.setattr(company_careers, "http_fetch", boom)
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", boom)
    snapshot = research.run_research(dry_run=True)
    plan = snapshot["acquisition_plan"]
    assert plan["company_pages"]["to_check"] == ["TEST_FIXTURE Co"]
    assert plan["search_provider"]["status"].startswith("AUTH_REQUIRED")
    assert not (isolated / "source_health.csv").exists() and not (isolated / "pages.csv").exists()
    assert not (isolated / "runs").exists() and not (isolated / "reports").exists()


def test_live_run_acquires_persists_and_records_health(isolated):
    snapshot = research.run_research()
    rows = list(csv.DictReader((isolated / "jobs.csv").open(encoding="utf-8")))
    assert len(rows) == 1
    row = rows[0]
    assert row["company"] == "TEST_FIXTURE Co" and row["freshness"] == "FRESH"
    assert row["extraction_method"] == "json_ld_jobposting" and row["application_url"] == "UNKNOWN"
    assert row["company_career_url"] == "https://co.example.test/careers" and row["primary_mode"] == "FULL_TIME"
    health = source_health.load_health(isolated / "source_health.csv")
    assert health["careers:TEST_FIXTURE Co"]["health_state"] == "VERIFIED"
    assert health["Remote OK"]["health_state"] == "BLOCKED"
    assert health["Brave Search API"]["health_state"] == "AUTH_REQUIRED"
    assert "Remote OK" in snapshot["sources_blocked"] and snapshot["new_opportunities"] == 1
    assert all("opportunities" not in h for h in snapshot["source_health"])  # no raw payloads in run records
    report = (isolated / "reports" / "daily_report.md").read_text(encoding="utf-8")
    for heading in ("## SEARCH", "## ACTION REQUIRED", "## SOURCE HEALTH", "## TOP CURRENT OPPORTUNITIES"):
        assert heading in report


def test_second_run_updates_instead_of_duplicating_and_respects_cooldown(isolated):
    research.run_research()
    second = research.run_research()
    assert len(list(csv.DictReader((isolated / "jobs.csv").open(encoding="utf-8")))) == 1
    assert second["updated_opportunities"] == 1 and second["new_opportunities"] == 0
    assert "Remote OK" in second["sources_in_cooldown"]


def test_ai_provider_is_never_called_by_acquisition(isolated, monkeypatch):
    from scripts.intelligence import claude_provider
    monkeypatch.setattr(claude_provider.ClaudeAIProvider, "analyze",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI during acquisition")))
    research.run_research()


def test_browser_queue_gets_url_verification_tasks_for_unverified_targets():
    from scripts.web.browser_queue import build_browser_queue
    tasks = build_browser_queue(region="gulf", limit_per_source=1)
    verify = {t["source"] for t in tasks if t["task_type"] == "VERIFY_COMPANY_CAREER_URL"}
    unverified = {t["company"] for t in company_careers.unverified_targets(company_careers.load_targets())}
    assert verify == unverified and verify
    assert all(t["url"] is None for t in tasks if t["task_type"] == "VERIFY_COMPANY_CAREER_URL")
    assert any(t["task_type"] == "OPEN_LINKEDIN_SEARCH" for t in tasks)


def test_acquisition_budget_has_defaults():
    limits = cfg_lib.acquisition_limits()
    assert limits["max_company_pages_per_run"] > 0 and limits["max_search_page_fetches"] > 0
    assert set(cfg_lib.search_limits()) == {"max_queries_per_run", "max_results_per_query", "max_pages",
                                             "max_requests_per_source"}


# --- security -------------------------------------------------------------------------

def test_no_credentials_in_config_or_new_code():
    secret = re.compile(r"(sk-ant-|sk-proj-|ghp_|github_pat_|AKIA[0-9A-Z]{12}|"
                        r"(api[_-]?key|token|secret|password)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{12,})", re.I)
    files = list(Path("config").glob("*.yaml")) + [Path(p) for p in (
        "scripts/web/brave_search.py", "scripts/web/search_discovery.py", "scripts/web/jobposting_parser.py",
        "scripts/lib/source_registry.py", "scripts/sources/company_careers.py")]
    for f in files:
        assert not secret.search(f.read_text(encoding="utf-8")), f


def test_run_is_not_success_when_every_live_source_failed():
    stats = {"number_new": 0, "number_collected": 0}
    health = [{"source": "Manual Import", "status": "EMPTY"},
              {"source": "Remote OK", "status": "UNAVAILABLE"}, {"source": "careers:X", "status": "UNAVAILABLE"}]
    assert research._determine_status(stats, health) == "PARTIAL"
    assert research._determine_status(stats, health[:1] + [{"source": "Remotive", "status": "EMPTY"}]) == "SUCCESS"
