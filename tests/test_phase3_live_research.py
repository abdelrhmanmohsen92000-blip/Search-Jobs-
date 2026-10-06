"""Phase 3 — live web research layer tests.

No test here depends on a live external website: HTTP calls are always
monkeypatched at the adapter boundary (http_get_json/http_get_text or
_post_with_retries-equivalent), exactly as the rest of this suite already does.
"""
import json

from scripts import research
from scripts.lib import source_health
from scripts.sources import company_careers
from scripts.sources.base import SourceRunResult


# --- Source health: persistent cross-run tracking -----------------------------------

def test_classify_status_maps_success_to_available():
    assert source_health.classify_status("SUCCESS") == "AVAILABLE"
    assert source_health.classify_status("EMPTY") == "AVAILABLE"


def test_classify_status_distinguishes_blocked_from_unavailable():
    assert source_health.classify_status("UNAVAILABLE", error="URLError: Tunnel connection failed: 403 Forbidden") == "BLOCKED"
    assert source_health.classify_status("UNAVAILABLE", error="URLError: timed out") == "UNAVAILABLE"


def test_classify_status_not_run_this_cycle_is_manual_not_a_failure():
    assert source_health.classify_status("NOT_RUN_THIS_CYCLE") == "MANUAL"


def test_classify_status_browser_required_is_manual():
    assert source_health.classify_status("BROWSER_REQUIRED") == "MANUAL"


def test_record_result_increments_counters():
    row = source_health.record_result("Remote OK", "SUCCESS")
    assert row["request_count"] == 1
    assert row["success_count"] == 1
    row2 = source_health.record_result("Remote OK", "UNAVAILABLE", error="timeout", existing=row)
    assert row2["request_count"] == 2
    assert row2["success_count"] == 1  # unchanged — the second call failed


def test_update_source_health_never_inflates_counters_for_manual_sources(tmp_path):
    csv_path = tmp_path / "source_health.csv"
    results = [
        {"source": "LinkedIn Jobs", "status": "BROWSER_REQUIRED", "error": None},
        {"source": "LinkedIn Jobs", "status": "BROWSER_REQUIRED", "error": None},
    ]
    health = source_health.update_source_health(results, csv_path=csv_path)
    assert health["LinkedIn Jobs"]["status"] == "MANUAL"
    assert health["LinkedIn Jobs"]["request_count"] in ("", None)  # never counted as an attempt


def test_update_source_health_persists_across_calls(tmp_path):
    csv_path = tmp_path / "source_health.csv"
    source_health.update_source_health([{"source": "Remote OK", "status": "SUCCESS", "error": None}], csv_path=csv_path)
    health = source_health.update_source_health([{"source": "Remote OK", "status": "UNAVAILABLE", "error": "blocked"}], csv_path=csv_path)
    row = health["Remote OK"]
    assert row["request_count"] == 2
    assert row["success_count"] == 1
    assert row["last_success"]  # preserved from the first call
    assert row["last_failure"]  # set by the second call


def test_update_source_health_never_hides_a_failing_source(tmp_path):
    csv_path = tmp_path / "source_health.csv"
    health = source_health.update_source_health(
        [{"source": "Indeed", "status": "UNAVAILABLE", "error": "blocked"}], csv_path=csv_path
    )
    assert health["Indeed"]["status"] in ("UNAVAILABLE", "BLOCKED")


# --- Company career pages: first-class, configurable source, never fabricated URL -----

def test_company_careers_never_fabricates_a_url(tmp_path):
    csv_path = tmp_path / "company_career_pages.csv"
    company_careers.add_company_source("Real Verified Co", "https://real-verified-co.example/careers",
                                        source_type="architecture_firm", csv_path=csv_path)
    rows = company_careers.load_company_sources(csv_path)
    assert len(rows) == 1
    assert rows[0]["career_url"] == "https://real-verified-co.example/careers"  # exactly what was supplied, nothing guessed


def test_company_careers_isolates_one_bad_entry(tmp_path, monkeypatch):
    csv_path = tmp_path / "company_career_pages.csv"
    company_careers.add_company_source("Good Co", "https://good.example/careers", csv_path=csv_path)
    company_careers.add_company_source("Bad Co", "https://bad.example/careers", csv_path=csv_path)

    def fake_fetch(self, query=None, limit=None):
        if query["company_name"] == "Bad Co":
            raise RuntimeError("simulated crash")
        return SourceRunResult(source=f"careers:{query['company_name']}", status="FETCHED_UNPARSED", raw_count=100)

    monkeypatch.setattr(company_careers.CompanyCareersAdapter, "fetch", fake_fetch)
    results = company_careers.run_configured_company_sources(csv_path=csv_path)
    assert len(results) == 2  # Bad Co's crash didn't stop Good Co from being processed
    statuses = {r.source: r.status for r in results}
    assert statuses["careers:Good Co"] == "FETCHED_UNPARSED"
    assert statuses["careers:Bad Co"] == "ERROR"


def test_company_careers_updates_last_checked_and_status(tmp_path, monkeypatch):
    csv_path = tmp_path / "company_career_pages.csv"
    company_careers.add_company_source("Test Co", "https://test.example/careers", csv_path=csv_path)
    monkeypatch.setattr(company_careers.CompanyCareersAdapter, "fetch",
                         lambda self, query=None, limit=None: SourceRunResult(source="careers:Test Co", status="UNAVAILABLE", error="blocked"))
    company_careers.run_configured_company_sources(csv_path=csv_path)
    row = company_careers.load_company_sources(csv_path)[0]
    assert row["last_status"] == "UNAVAILABLE"
    assert row["last_checked"]


def test_company_careers_skips_disabled_rows(tmp_path, monkeypatch):
    csv_path = tmp_path / "company_career_pages.csv"
    company_careers.add_company_source("Disabled Co", "https://disabled.example/careers", enabled=False, csv_path=csv_path)
    calls = []
    monkeypatch.setattr(company_careers.CompanyCareersAdapter, "fetch",
                         lambda self, query=None, limit=None: calls.append(query) or SourceRunResult(source="x", status="SUCCESS"))
    results = company_careers.run_configured_company_sources(csv_path=csv_path)
    assert results == []
    assert calls == []


def test_company_career_pages_example_file_well_formed():
    import yaml
    data = yaml.safe_load(open("config/company_career_pages.example.yaml"))
    assert data["companies"][0]["career_url"].startswith("EXAMPLE")  # clearly marked, not a real URL


# --- Research run orchestrator: snapshot persistence, honest status -------------------

def test_run_research_dry_run_saves_no_snapshot(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib
    monkeypatch.setattr(paths_lib, "DATA_RESEARCH_RUNS", tmp_path / "runs")
    snapshot = research.run_research(region="gulf", dry_run=True)
    assert snapshot["status"] == "DRY_RUN"
    assert not (tmp_path / "runs").exists()


def _patch_research_paths(tmp_path, monkeypatch):
    """Isolates every path scripts.daily_research.run() can touch, including
    the two that bit us during development of this test: storage.save_run_snapshot
    always writes under paths.DATA_DIR (not paths.DATA_PROCESSED — that
    constant is a separate, already-resolved Path and isn't what
    save_run_snapshot reads), and storage.backup_file always backs up into
    paths.DATA_ARCHIVE regardless of where the CSV itself lives. Missing
    either leaks real files into the repository's data/ directory during a
    'fully isolated' test — caught by this test suite leaving stray files
    behind, which is exactly why every path is listed explicitly here.
    """
    from scripts.lib import paths as paths_lib
    fake_jobs = tmp_path / "jobs.csv"
    fake_jobs.write_text("id\n", encoding="utf-8")
    monkeypatch.setattr(paths_lib, "JOBS_CSV", fake_jobs)
    monkeypatch.setattr(paths_lib, "SOURCE_HEALTH_CSV", tmp_path / "source_health.csv")
    monkeypatch.setattr(paths_lib, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths_lib, "DATA_PROCESSED", tmp_path / "data" / "processed")
    monkeypatch.setattr(paths_lib, "DATA_ARCHIVE", tmp_path / "data" / "archive")
    monkeypatch.setattr(paths_lib, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(paths_lib, "NETWORKING_CSV", tmp_path / "networking.csv")
    monkeypatch.setattr(paths_lib, "DATA_RESEARCH_RUNS", tmp_path / "runs")
    (tmp_path / "networking.csv").write_text("person\n", encoding="utf-8")
    # Never make a real network call in the normal test suite — mock the one
    # live adapter under test at its HTTP boundary, with an immediate,
    # deterministic failure (no retry/backoff delay).
    monkeypatch.setattr("scripts.sources.remoteok.http_get_json", lambda *a, **k: (None, "mocked: blocked"))


def test_run_research_persists_snapshot_with_required_fields(tmp_path, monkeypatch):
    _patch_research_paths(tmp_path, monkeypatch)

    snapshot = research.run_research(region="gulf", source_filter="Remote OK", dry_run=False)

    required = {"run_id", "started_at", "completed_at", "queries", "providers",
                "results_count", "new_jobs", "duplicates", "errors", "source_health", "status"}
    assert required.issubset(snapshot.keys())
    assert snapshot["status"] in ("SUCCESS", "PARTIAL", "FAILED")
    from pathlib import Path
    assert Path(snapshot["snapshot_path"]).exists()


def test_run_research_never_hides_errors(tmp_path, monkeypatch):
    _patch_research_paths(tmp_path, monkeypatch)

    snapshot = research.run_research(region="gulf", source_filter="Remote OK", dry_run=False)
    # the mocked failure above must appear as an error, never silently dropped
    assert any(e["source"] == "Remote OK" for e in snapshot["errors"])


def test_determine_status_success_when_source_reaches_but_finds_nothing():
    stats = {"number_new": 0, "number_collected": 0}
    source_health_list = [{"status": "EMPTY"}]
    assert research._determine_status(stats, source_health_list) == "SUCCESS"


def test_determine_status_failed_when_everything_fails():
    stats = {"number_new": 0, "number_collected": 0}
    source_health_list = [{"status": "UNAVAILABLE"}, {"status": "ERROR"}]
    assert research._determine_status(stats, source_health_list) == "FAILED"


def test_determine_status_success_with_new_jobs_found():
    stats = {"number_new": 3, "number_collected": 5}
    source_health_list = [{"status": "SUCCESS"}]
    assert research._determine_status(stats, source_health_list) == "SUCCESS"


def test_load_research_runs_reads_all_persisted_snapshots(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "a.json").write_text(json.dumps({"run_id": "a", "status": "SUCCESS"}), encoding="utf-8")
    (runs_dir / "b.json").write_text(json.dumps({"run_id": "b", "status": "FAILED"}), encoding="utf-8")
    monkeypatch.setattr(paths_lib, "DATA_RESEARCH_RUNS", runs_dir)
    runs = research.load_research_runs()
    assert {r["run_id"] for r in runs} == {"a", "b"}


# --- Query limits: no explosion -------------------------------------------------------

def test_search_limits_has_all_four_keys():
    from scripts.lib import config as cfg_lib
    limits = cfg_lib.search_limits()
    assert set(limits) == {"max_queries_per_run", "max_results_per_query", "max_pages", "max_requests_per_source"}


def test_build_query_plan_defaults_to_max_queries_per_run():
    from scripts import search_config
    plan = search_config.build_query_plan(region="global")
    from scripts.lib import config as cfg_lib
    assert len(plan) <= cfg_lib.search_limits()["max_queries_per_run"]


def test_build_query_plan_limit_zero_means_unlimited():
    from scripts import search_config
    plan_default = search_config.build_query_plan(region="gulf")
    plan_unlimited = search_config.build_query_plan(region="gulf", limit=0)
    assert len(plan_unlimited) >= len(plan_default)


def test_build_query_plan_sampling_preserves_title_diversity():
    from scripts import search_config
    plan = search_config.build_query_plan(region="global", limit=200)
    distinct_titles = {q["title"] for q in plan}
    assert len(distinct_titles) > 1  # must not collapse to a single title's combinations


# --- Real-data-policy safety net: backup_file never leaks outside its own root -------

def test_backup_file_never_writes_into_real_data_archive_for_a_tmp_path(tmp_path):
    """Regression test for a real leak found during Phase 3 development:
    a CSV living outside this repository (e.g. a pytest tmp_path, which
    happens to share a real tracker's filename) must never get backed up
    into the repository's own data/archive/ — it must stay fully contained
    in its own location.
    """
    from scripts.lib import storage as storage_lib

    csv_path = tmp_path / "source_health.csv"  # deliberately shares a real tracker's filename
    csv_path.write_text("source,status\n", encoding="utf-8")

    dest = storage_lib.backup_file(csv_path)

    assert dest is not None
    assert str(tmp_path) in str(dest)  # archived next to itself
    from scripts.lib import paths as paths_lib
    assert not str(dest).startswith(str(paths_lib.DATA_ARCHIVE))  # never the real repo archive


def test_backup_file_still_archives_a_real_repo_path_normally(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib, storage as storage_lib

    fake_archive = tmp_path / "archive"
    monkeypatch.setattr(paths_lib, "DATA_ARCHIVE", fake_archive)
    real_looking_path = paths_lib.ROOT / "tracking" / "_phase3_test_backup_regression.csv"
    real_looking_path.write_text("a,b\n", encoding="utf-8")
    try:
        dest = storage_lib.backup_file(real_looking_path)
        assert dest is not None
        assert str(dest).startswith(str(fake_archive))  # still uses the (patched) real archive dir
    finally:
        real_looking_path.unlink(missing_ok=True)


def test_remotive_adapter_caps_requests_per_source(monkeypatch):
    from scripts.sources.remotive import RemotiveAdapter
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return {"jobs": []}, None

    monkeypatch.setattr("scripts.sources.remotive.http_get_json", fake_get)
    monkeypatch.setattr("scripts.sources.remotive.cfg_lib.search_limits", lambda *a, **k: {"max_requests_per_source": 2})
    RemotiveAdapter().fetch(search_terms=["a", "b", "c", "d", "e"])
    assert len(calls) == 2
