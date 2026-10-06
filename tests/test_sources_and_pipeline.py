"""V1.2 tests: source adapters, search query generation, pipeline stats,
dry-run behavior, and the no-fake-data guarantee.
"""
import json

from scripts import daily_research, search_config
from scripts.sources.base import SourceRunResult
from scripts.sources.remoteok import RemoteOKAdapter
from scripts.sources.remotive import RemotiveAdapter


class _FakeHTTPError(Exception):
    pass


def test_remoteok_adapter_success_with_monkeypatched_http(monkeypatch):
    sample = [
        {"legend": "this is the schema"},  # no id -> filtered out
        {"id": "1", "position": "BIM Architect", "company": "Acme", "url": "https://remoteok.com/1",
         "tags": ["revit", "bim"], "date": "2026-01-01"},
        {"id": "2", "position": "Plumber", "company": "Beta", "url": "https://remoteok.com/2", "tags": []},
    ]
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", lambda *a, **k: (sample, None))
    result = RemoteOKAdapter().fetch()
    assert result.status == "SUCCESS"
    assert len(result.opportunities) == 1
    assert result.opportunities[0]["company"] == "Acme"


def test_remoteok_adapter_unavailable_on_network_failure(monkeypatch):
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", lambda *a, **k: (None, "URLError: blocked"))
    result = RemoteOKAdapter().fetch()
    assert result.status == "UNAVAILABLE"
    assert result.error == "URLError: blocked"
    assert result.opportunities == []  # never fabricates results on failure


def test_remoteok_adapter_malformed_response_reports_error(monkeypatch):
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", lambda *a, **k: ({"not": "a list"}, None))
    result = RemoteOKAdapter().fetch()
    assert result.status == "ERROR"
    assert result.opportunities == []


def test_remoteok_adapter_empty_when_nothing_relevant(monkeypatch):
    sample = [{"id": "1", "position": "Plumber", "company": "Beta", "tags": []}]
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", lambda *a, **k: (sample, None))
    result = RemoteOKAdapter().fetch()
    assert result.status == "EMPTY"


def test_remotive_adapter_success_with_monkeypatched_http(monkeypatch):
    def fake_get(url, **kwargs):
        return {"jobs": [{"id": 1, "title": "BIM Coordinator", "company_name": "Acme", "url": "https://remotive.com/1",
                           "candidate_required_location": "Worldwide", "tags": ["bim"]}]}, None

    monkeypatch.setattr("scripts.sources.remotive.http_get_json", fake_get)
    result = RemotiveAdapter().fetch()
    assert result.status == "SUCCESS"
    assert result.opportunities[0]["company"] == "Acme"
    assert result.opportunities[0]["country"] is None  # "Worldwide" normalized to no fixed country


def test_remotive_adapter_all_terms_fail_is_unavailable(monkeypatch):
    monkeypatch.setattr("scripts.sources.remotive.http_get_json", lambda *a, **k: (None, "timeout"))
    result = RemotiveAdapter().fetch()
    assert result.status == "UNAVAILABLE"


def test_source_run_result_never_fabricates_on_failure():
    r = SourceRunResult(source="x", status="UNAVAILABLE", error="blocked")
    assert r.opportunities == []


def test_global_region_alias_covers_all_regions():
    plan_global = search_config.build_query_plan(region="global", limit=50)
    plan_none = search_config.build_query_plan(region=None, limit=50)
    assert {q["region"] for q in plan_global} == {q["region"] for q in plan_none}
    assert len({q["region"] for q in plan_global}) > 1


def test_regional_query_generation_restricts_to_one_region():
    plan = search_config.build_query_plan(region="europe", limit=50)
    assert all(q["region"] == "europe" for q in plan)


def test_remote_search_uses_worldwide_remote_region_and_remote_employment_type():
    plan = search_config.build_query_plan(remote_only=True, limit=20)
    assert all(q["region"] == "worldwide_remote" for q in plan)
    assert all(q["employment_type"] == "Remote" for q in plan)


def test_freelance_search_uses_freelance_sources_only():
    plan = search_config.build_query_plan(freelance_only=True, limit=20)
    sources = {q["source"] for q in plan}
    job_board_only_names = {"Remote OK", "Remotive", "Indeed"}
    assert not (sources & job_board_only_names)


def test_source_filter_restricts_to_named_source():
    plan = search_config.build_query_plan(region="gulf", source_filter="Remote OK", limit=20)
    assert plan
    assert {q["source"] for q in plan} == {"Remote OK"}


def test_unknown_region_raises():
    import pytest
    with pytest.raises(ValueError):
        search_config.build_query_plan(region="atlantis")


def test_daily_research_dry_run_touches_no_trackers(tmp_path, monkeypatch):
    # point jobs.csv at a throwaway file so this test can never touch real tracking data
    fake_jobs = tmp_path / "jobs.csv"
    fake_jobs.write_text("id\n", encoding="utf-8")
    monkeypatch.setattr("scripts.lib.paths.JOBS_CSV", fake_jobs)

    result = daily_research.run(region="gulf", dry_run=True)
    assert result["dry_run"] is True
    assert "query_summary" in result
    # untouched: still just the header we wrote
    assert fake_jobs.read_text(encoding="utf-8") == "id\n"


def test_daily_research_dry_run_returns_no_opportunities():
    result = daily_research.run(region="europe", dry_run=True)
    assert "scored" not in result  # dry run never produces/claims opportunity data


def test_build_cycle_stats_never_fabricates_counts():
    health = [
        {"source": "Remote OK", "status": "UNAVAILABLE", "error": "blocked", "opportunities": [], "raw_count": 0},
        {"source": "Manual Import", "status": "EMPTY", "error": None, "opportunities": [], "raw_count": 0},
    ]
    stats = daily_research.build_cycle_stats([], [], [], [], health)
    assert stats["sources_successful"] == []
    assert stats["sources_failed"] == ["Remote OK"]
    assert stats["number_new"] == 0
    assert stats["number_collected"] == 0
