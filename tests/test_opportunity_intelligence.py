"""Phase 4.2 — Opportunity Intelligence & Multi-Mode Resolution.

Every opportunity here is a synthetic TEST_FIXTURE; every file write goes to
tmp_path. No network access. Settings are built from an in-test career state
so results don't depend on edits to the real config/career_state.yaml
(except the one test that checks the real file loads).
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import career_intelligence, career_search_modes, daily_research, research  # noqa: E402
from scripts.intelligence import opportunity_priority as prio  # noqa: E402
from scripts.lib import career_state, opportunity_modes as modes  # noqa: E402

STATE = {
    "current_primary_goal": "FULL_TIME",
    "search_modes": {
        "FULL_TIME": {"enabled": True, "priority": "HIGH", "frequency": "daily", "employment_types": ["Full-time"]},
        "REMOTE_FULL_TIME": {"enabled": True, "priority": "MEDIUM", "frequency": "daily", "employment_types": ["Remote"]},
        "CONTRACT": {"enabled": True, "priority": "LOW", "frequency": "weekly", "employment_types": ["Contract"]},
        "PART_TIME": {"enabled": False, "priority": "LOW", "frequency": "weekly", "employment_types": ["Part-time"]},
        "FREELANCE": {"enabled": True, "priority": "LOW", "frequency": "weekly",
                      "employment_types": ["Freelance"], "freelance_only": True},
    },
    "ranking": {
        "primary_mode_precedence": ["REMOTE_FULL_TIME", "FULL_TIME", "FREELANCE", "PART_TIME", "CONTRACT"],
        "current_goal_score": 100, "mode_priority_scores": {"HIGH": 100, "MEDIUM": 70, "LOW": 40},
        "inactive_mode_score": 20, "unknown_mode_score": 50, "mode_weight_floor": 0.75,
        "career_priority_bands": {"HIGH": 75, "MEDIUM": 55}, "outside_goal_max_label": "MEDIUM",
    },
    "exceptional": {"enabled": True, "min_match_score": 92, "min_career_value": 9,
                    "career_value_min_match_score": 80, "min_compensation": 9},
    "alerts": {"suppress_high_match_outside_goal": True},
}


@pytest.fixture
def settings():
    return prio.load_settings(STATE)


def fixture_opp(title="TEST_FIXTURE BIM Architect", company="TEST_FIXTURE Co", match=80.0, **extra):
    opp = {"id": f"{company}|{title}", "job_title": title, "company": company, "match_score": match,
           "scoring_result": {"sub_scores_explicit": False, "career_value": 5, "compensation": 5}}
    opp.update(extra)
    return opp


def classified(settings, **kwargs):
    opp = fixture_opp(**kwargs)
    modes.apply_mode_classification(opp, precedence=settings["ranking"]["primary_mode_precedence"])
    return prio.evaluate_opportunity(opp, settings)


# --- 1/2. classification: explicit evidence only -----------------------------

@pytest.mark.parametrize("opp,expected", [
    ({"job_title": "BIM Architect", "description": "This is a full-time position."}, ["FULL_TIME"]),
    ({"job_title": "Remote full-time BIM Architect"}, ["REMOTE_FULL_TIME", "FULL_TIME"]),
    ({"job_title": "Freelance architectural visualization project"}, ["FREELANCE"]),
    ({"job_title": "BIM Modeler", "description": "Part-time, 20 hours a week."}, ["PART_TIME"]),
    ({"job_title": "BIM Modeler", "description": "6-month contract based in Riyadh."}, ["CONTRACT"]),
    ({"job_title": "Architect needed"}, []),
    ({"job_title": "BIM Coordinator", "employment_type": "Full-time", "remote": True}, ["REMOTE_FULL_TIME", "FULL_TIME"]),
    ({"job_title": "BIM Coordinator", "employment_type": "Contract"}, ["CONTRACT"]),
])
def test_classification_from_explicit_evidence(opp, expected):
    assert modes.classify_modes(opp)[0] == expected


def test_contract_documents_is_not_contract_employment():
    assert modes.classify_modes({"job_title": "Architect", "description": "Prepare contract documents."})[0] == []


def test_remote_project_sites_is_not_remote_work():
    matched, _ = modes.classify_modes({"job_title": "Full-time Architect", "description": "Travel to remote project sites."})
    assert matched == ["FULL_TIME"]


def test_remote_alone_does_not_imply_full_time():
    assert modes.classify_modes({"job_title": "BIM Architect", "remote": True})[0] == []


def test_mode_match_reasons_explain_each_mode():
    _, reasons = modes.classify_modes({"job_title": "Remote full-time BIM Architect"})
    assert any("Full-time" in r for r in reasons["FULL_TIME"])
    assert any("Remote" in r for r in reasons["REMOTE_FULL_TIME"])
    assert any("Full-time" in r for r in reasons["REMOTE_FULL_TIME"])


def test_discovering_search_mode_is_never_evidence():
    opp = {"job_title": "Architect needed"}
    modes.apply_mode_classification(opp, discovered_via_mode="FULL_TIME")
    assert opp["matched_modes"] == []
    assert opp["primary_mode"] == "UNKNOWN"
    assert opp["discovered_via_modes"] == ["FULL_TIME"]


# --- 3. primary mode -----------------------------------------------------------

def test_primary_mode_is_deterministic_by_precedence():
    assert modes.resolve_primary_mode(["CONTRACT", "FULL_TIME", "REMOTE_FULL_TIME"]) == "REMOTE_FULL_TIME"
    assert modes.resolve_primary_mode(["CONTRACT", "FREELANCE"]) == "FREELANCE"


def test_primary_mode_honours_configured_precedence():
    assert modes.resolve_primary_mode(["FULL_TIME", "CONTRACT"], precedence=["CONTRACT", "FULL_TIME"]) == "CONTRACT"


def test_primary_mode_unknown_without_evidence():
    assert modes.resolve_primary_mode([]) == "UNKNOWN"


# --- 4/5/6. one canonical opportunity, mode-aware dedup and merging ------------

def _raw(**extra):
    base = {"source": "TEST_FIXTURE source", "source_url": "https://example.test/job/1",
            "job_title": "TEST_FIXTURE BIM Architect", "company": "TEST_FIXTURE Co", "country": "Saudi Arabia"}
    base.update(extra)
    return base


def test_same_job_found_twice_in_a_run_is_one_record_with_merged_modes(settings):
    raws = [_raw(description="Full-time role."), _raw(description="Full-time, fully remote role.")]
    scored, _, duplicates = daily_research.normalize_and_score(raws, profile={}, discovered_via_mode="FULL_TIME",
                                                               settings=settings)
    assert len(scored) == 1 and len(duplicates) == 1
    assert scored[0]["matched_modes"] == ["REMOTE_FULL_TIME", "FULL_TIME"]
    assert scored[0]["primary_mode"] == "REMOTE_FULL_TIME"


def test_mode_is_not_part_of_the_identity_key(settings):
    a, _, _ = daily_research.normalize_and_score([_raw(description="Full-time.")], profile={},
                                                 discovered_via_mode="FULL_TIME", settings=settings)
    b, _, _ = daily_research.normalize_and_score([_raw(description="Full-time.")], profile={},
                                                 discovered_via_mode="REMOTE_FULL_TIME", settings=settings)
    assert a[0]["id"] == b[0]["id"]


def test_duplicate_at_other_url_keeps_its_source_as_alternate(settings):
    raws = [_raw(), _raw(source="TEST_FIXTURE company careers", source_url="https://example.test/careers/1")]
    scored, _, _ = daily_research.normalize_and_score(raws, profile={}, settings=settings)
    assert len(scored) == 1
    assert {"source": "TEST_FIXTURE company careers", "source_url": "https://example.test/careers/1"} \
        in scored[0]["alternate_sources"]


def test_merge_is_union_and_never_drops_stronger_evidence():
    first = {"matched_modes": ["FULL_TIME"], "mode_match_reasons": {"FULL_TIME": ["a"]}, "discovered_via_modes": ["FULL_TIME"]}
    weaker = {"matched_modes": [], "mode_match_reasons": {}, "discovered_via_modes": ["CONTRACT"]}
    remote = {"matched_modes": ["REMOTE_FULL_TIME", "FULL_TIME"],
              "mode_match_reasons": {"REMOTE_FULL_TIME": ["b"], "FULL_TIME": ["a"]}, "discovered_via_modes": ["REMOTE_FULL_TIME"]}
    modes.merge_mode_data(first, weaker)
    assert first["matched_modes"] == ["FULL_TIME"]
    modes.merge_mode_data(first, remote)
    assert first["matched_modes"] == ["REMOTE_FULL_TIME", "FULL_TIME"]
    assert first["primary_mode"] == "REMOTE_FULL_TIME"
    assert first["mode_match_reasons"]["FULL_TIME"] == ["a"]
    assert first["discovered_via_modes"] == ["FULL_TIME", "CONTRACT", "REMOTE_FULL_TIME"]


# --- persistence: repeated discovery never duplicates rows ------------------

def _row(settings, **raw_extra):
    scored, _, _ = daily_research.normalize_and_score([_raw(**raw_extra)], profile={}, settings=settings)
    return daily_research.opportunity_to_jobs_row(scored[0])


def test_rediscovery_under_another_mode_updates_one_row(tmp_path, settings):
    jobs = tmp_path / "jobs.csv"
    full_time = daily_research.normalize_and_score([_raw(description="Full-time.")], profile={},
                                                   discovered_via_mode="FULL_TIME", settings=settings)[0]
    remote = daily_research.normalize_and_score([_raw(description="Full-time, fully remote.")], profile={},
                                                discovered_via_mode="REMOTE_FULL_TIME", settings=settings)[0]
    assert daily_research.upsert_jobs_rows([daily_research.opportunity_to_jobs_row(full_time[0])], jobs, settings) == (1, 0)
    assert daily_research.upsert_jobs_rows([daily_research.opportunity_to_jobs_row(remote[0])], jobs, settings) == (0, 1)
    rows = list(csv.DictReader(jobs.open(encoding="utf-8")))
    assert len(rows) == 1
    reloaded = career_intelligence.opportunity_from_jobs_row(rows[0])
    assert reloaded["matched_modes"] == ["REMOTE_FULL_TIME", "FULL_TIME"]
    assert reloaded["discovered_via_modes"] == ["FULL_TIME", "REMOTE_FULL_TIME"]
    assert reloaded["primary_mode"] == "REMOTE_FULL_TIME"


def test_repeated_identical_discovery_stays_one_row(tmp_path, settings):
    jobs = tmp_path / "jobs.csv"
    row = _row(settings, description="Full-time.")
    for _ in range(3):
        daily_research.upsert_jobs_rows([row], jobs, settings)
    assert len(list(csv.DictReader(jobs.open(encoding="utf-8")))) == 1


def test_rediscovery_at_different_url_merges_and_keeps_both_urls(tmp_path, settings):
    jobs = tmp_path / "jobs.csv"
    daily_research.upsert_jobs_rows([_row(settings, description="Full-time.")], jobs, settings)
    other = _row(settings, source_url="https://example.test/careers/1", description="Contract position.")
    daily_research.upsert_jobs_rows([other], jobs, settings)
    rows = list(csv.DictReader(jobs.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["source_url"] == "https://example.test/job/1"
    assert "https://example.test/careers/1" in modes.parse_list(rows[0]["alternate_source_urls"])
    assert modes.parse_list(rows[0]["matched_modes"]) == ["FULL_TIME", "CONTRACT"]


def test_blank_values_never_overwrite_existing_evidence(tmp_path, settings):
    jobs = tmp_path / "jobs.csv"
    daily_research.upsert_jobs_rows([_row(settings, employment_type="Full-time")], jobs, settings)
    daily_research.upsert_jobs_rows([_row(settings)], jobs, settings)
    assert list(csv.DictReader(jobs.open(encoding="utf-8")))[0]["employment_type"] == "Full-time"


# --- 7. current career goal priority (match_score untouched) -----------------

def test_match_score_is_never_modified(settings):
    opp = classified(settings, match=88.0, description="Freelance project.")
    assert opp["match_score"] == 88.0


def test_full_time_gets_goal_priority_over_secondary_modes(settings):
    full_time = classified(settings, description="Full-time.")
    freelance = classified(settings, description="Freelance project.")
    contract = classified(settings, description="6-month contract.")
    part_time = classified(settings, description="Part-time role.")
    assert full_time["mode_priority_score"] == 100
    assert freelance["mode_priority_score"] == 40
    assert contract["mode_priority_score"] == 40
    assert part_time["mode_priority_score"] == 20  # PART_TIME is disabled in the fixture state
    assert full_time["career_priority_score"] > freelance["career_priority_score"]


def test_unknown_mode_is_neutral_not_outside_goal(settings):
    opp = classified(settings, title="TEST_FIXTURE Architect needed")
    assert opp["primary_mode"] == "UNKNOWN"
    assert opp["mode_priority_score"] == 50
    assert opp["outside_current_goal"] is False


def test_current_goal_is_read_from_career_state_not_hard_coded():
    state = {**STATE, "current_primary_goal": "FREELANCE"}
    s = prio.load_settings(state)
    freelance = classified(s, description="Freelance project.")
    full_time = classified(s, description="Full-time.")
    assert freelance["mode_priority_score"] == 100
    assert full_time["outside_current_goal"] is True


def test_outside_goal_label_is_capped(settings):
    opp = classified(settings, match=99.0, description="Freelance project.")
    assert opp["career_priority"] == "MEDIUM"


# --- 8/12/13. ranking ----------------------------------------------------------

def test_best_match_vs_best_current_priority(settings):
    freelance = classified(settings, title="TEST_FIXTURE Freelance BIM Architect", match=91.0)
    full_time = classified(settings, title="TEST_FIXTURE BIM Architect", match=89.0, description="Full-time.")
    ranked = prio.rank_opportunities([freelance, full_time], settings)
    assert ranked["best_match"] is freelance
    assert ranked["best_current"] is full_time


def test_mode_never_lifts_a_poor_match_over_a_strong_one(settings):
    poor = classified(settings, title="TEST_FIXTURE Full-time Drafter", match=42.0)
    strong = classified(settings, title="TEST_FIXTURE Freelance BIM Lead", match=95.0)
    ranked = prio.rank_opportunities([poor, strong], settings)
    assert ranked["top_current"][0] is strong


def test_ranking_is_deterministic(settings):
    opps = [classified(settings, company=f"TEST_FIXTURE {i}", match=80.0, description="Full-time.") for i in range(5)]
    first = [o["id"] for o in prio.rank_opportunities(opps, settings)["top_current"]]
    second = [o["id"] for o in prio.rank_opportunities(list(reversed(opps)), settings)["top_current"]]
    assert first == second


# --- 9/10/11. exceptional opportunities ---------------------------------------

def test_exceptional_threshold_boundary(settings):
    assert classified(settings, match=92.0)["exceptional_opportunity"] is True
    assert classified(settings, match=91.9)["exceptional_opportunity"] is False


def test_exceptional_threshold_is_configurable():
    s = prio.load_settings({**STATE, "exceptional": {**STATE["exceptional"], "min_match_score": 80}})
    assert classified(s, match=81.0)["exceptional_opportunity"] is True


def test_exceptional_disabled_never_flags():
    s = prio.load_settings({**STATE, "exceptional": {"enabled": False}})
    assert classified(s, match=99.0)["exceptional_opportunity"] is False


def test_missing_exceptional_config_defaults_to_off():
    s = prio.load_settings({"current_primary_goal": "FULL_TIME"})
    assert classified(s, match=99.0)["exceptional_opportunity"] is False


def test_exceptional_outside_current_goal_is_surfaced_with_note(settings):
    opp = classified(settings, title="TEST_FIXTURE Freelance BIM Lead", match=98.0)
    ranked = prio.rank_opportunities([opp, classified(settings, match=89.0, description="Full-time.")], settings)
    assert opp in ranked["exceptional"]
    assert opp["outside_current_goal"] is True
    text = "\n".join(daily_research.opportunity_intelligence_lines([opp], settings))
    assert "Outside current primary mode (FULL_TIME)" in text
    assert "exceptional threshold" in text


def test_career_value_reason_requires_explicitly_assessed_sub_scores(settings):
    defaulted = classified(settings, match=85.0, scoring_result={"sub_scores_explicit": False, "career_value": 10})
    assessed = classified(settings, match=85.0, scoring_result={"sub_scores_explicit": True, "career_value": 10})
    assert defaulted["exceptional_opportunity"] is False
    assert assessed["exceptional_reasons"] == ["unusually_high_career_value"]


def test_exceptional_reasons_are_evidence_only(settings):
    opp = classified(settings, match=95.0)
    assert opp["exceptional_reasons"] == ["exceptional_match"]
    for invented in ("prestigious_company", "major_project", "international_exposure", "rare_role",
                     "strategic_market_entry"):
        assert invented not in opp["exceptional_reasons"]


def test_portfolio_alignment_reason_needs_direct_high_relevance_project(settings):
    with_direct = classified(settings, match=95.0, portfolio_evidence_summary={
        "direct_project_matches": [{"project": "Supply Chain - Riyadh", "relevance": "HIGH"}]})
    capability_only = classified(settings, match=95.0, portfolio_evidence_summary={
        "direct_project_matches": [], "profile_capability_matches": [{"capability": "Autodesk Revit"}]})
    assert "strong_portfolio_alignment" in with_direct["exceptional_reasons"]
    assert "strong_portfolio_alignment" not in capability_only["exceptional_reasons"]


def test_supporting_reasons_never_make_an_ordinary_job_exceptional(settings):
    opp = classified(settings, match=70.0, title="TEST_FIXTURE Remote full-time BIM Architect",
                     scoring_result={"sub_scores_explicit": True, "career_value": 5, "compensation": 10},
                     portfolio_evidence_summary={"direct_project_matches": [{"project": "X", "relevance": "HIGH"}]})
    assert opp["exceptional_opportunity"] is False
    assert opp["exceptional_reasons"] == []


# --- 15. alerts ------------------------------------------------------------------

@pytest.fixture
def isolated_alert_paths(tmp_path, monkeypatch):
    from scripts.lib import paths as paths_lib
    applications = tmp_path / "applications.csv"
    applications.write_text("status\n", encoding="utf-8")
    monkeypatch.setattr(paths_lib, "APPLICATIONS_CSV", applications)
    monkeypatch.setattr(paths_lib, "ALERTS_CSV", tmp_path / "alerts.csv")
    monkeypatch.setattr(paths_lib, "DATA_DIR", tmp_path)


def test_exceptional_outside_goal_still_alerts_with_explanation(isolated_alert_paths, settings):
    opp = classified(settings, title="TEST_FIXTURE Freelance BIM Lead", match=96.0)
    alerts = career_intelligence.generate_alerts([opp], settings=settings)
    exceptional = [a for a in alerts if a["alert_type"] == "NEW_EXCEPTIONAL_OPPORTUNITY"]
    assert len(exceptional) == 1
    assert "Mode: FREELANCE" in exceptional[0]["details"]
    assert "Current goal: FULL_TIME" in exceptional[0]["details"]
    assert "outside your current primary mode" in exceptional[0]["details"]


def test_non_exceptional_outside_goal_high_match_is_not_alerted(isolated_alert_paths, settings):
    opp = classified(settings, title="TEST_FIXTURE Freelance BIM Architect", match=88.0)
    assert career_intelligence.generate_alerts([opp], settings=settings) == []


def test_unknown_mode_high_match_still_alerts(isolated_alert_paths, settings):
    opp = classified(settings, title="TEST_FIXTURE BIM Architect", match=88.0)
    assert [a["alert_type"] for a in career_intelligence.generate_alerts([opp], settings=settings)] == ["HIGH_MATCH_JOB"]


def test_in_goal_high_match_alerts(isolated_alert_paths, settings):
    opp = classified(settings, match=88.0, description="Full-time.")
    assert [a["alert_type"] for a in career_intelligence.generate_alerts([opp], settings=settings)] == ["HIGH_MATCH_JOB"]


# --- 16. portfolio evidence independence -------------------------------------

def test_mode_classification_does_not_change_portfolio_evidence():
    import yaml
    profile = yaml.safe_load(Path("config/profile_skills.yaml").read_text())
    profile["portfolio_projects"] = yaml.safe_load(Path("config/portfolio_projects.yaml").read_text())["portfolio_projects"]
    base = {"source": "TEST_FIXTURE", "job_title": "TEST_FIXTURE BIM Coordinator", "company": "TEST_FIXTURE Co",
            "country": "Saudi Arabia", "project_types": ["Healthcare"], "software_required": ["Autodesk Revit"]}
    plain, _, _ = daily_research.normalize_and_score([base], profile=profile)
    with_mode, _, _ = daily_research.normalize_and_score([{**base, "description": "Remote full-time role."}],
                                                         profile=profile, discovered_via_mode="FULL_TIME")
    assert with_mode[0]["matched_modes"] == ["REMOTE_FULL_TIME", "FULL_TIME"]
    assert plain[0]["portfolio_evidence_summary"] == with_mode[0]["portfolio_evidence_summary"]


# --- 18. CLI: --mode / --all-modes / --force / --dry-run -----------------------

def _now_runs(*names):
    import datetime as _dt
    return {n: _dt.datetime.now().isoformat(timespec="seconds") for n in names}


def test_select_mode_is_case_insensitive():
    sel = career_search_modes.select_modes("full_time", state=STATE, runs={})
    assert [m["name"] for m in sel["selected"]] == ["FULL_TIME"]


def test_select_mode_skips_when_not_due():
    sel = career_search_modes.select_modes("freelance", state=STATE, runs=_now_runs("FREELANCE"))
    assert sel["selected"] == []
    assert "use --force" in sel["skipped"][0]["reason"]


def test_force_bypasses_due_check():
    sel = career_search_modes.select_modes("freelance", force=True, state=STATE, runs=_now_runs("FREELANCE"))
    assert [m["name"] for m in sel["selected"]] == ["FREELANCE"]


def test_force_does_not_enable_a_disabled_mode():
    sel = career_search_modes.select_modes("part_time", force=True, state=STATE, runs={})
    assert sel["selected"] == [] and "disabled" in sel["error"]


def test_unknown_mode_is_refused():
    assert "Unknown mode" in career_search_modes.select_modes("astronaut", state=STATE, runs={})["error"]


def test_all_modes_respects_due_unless_forced():
    runs = _now_runs("CONTRACT", "FREELANCE")
    due = career_search_modes.select_modes(all_modes=True, state=STATE, runs=runs)
    forced = career_search_modes.select_modes(all_modes=True, force=True, state=STATE, runs=runs)
    assert [m["name"] for m in due["selected"]] == ["FULL_TIME", "REMOTE_FULL_TIME"]
    assert {s["mode"] for s in due["skipped"]} == {"CONTRACT", "FREELANCE"}
    assert len(forced["selected"]) == 4


def _cli(argv):
    import career_hunter
    args = career_hunter.build_parser().parse_args(argv)
    args.func(args)


def test_cli_research_force_dry_run_runs_a_not_due_mode(tmp_path, monkeypatch, capsys):
    runs_file = tmp_path / "career_mode_runs.json"
    runs_file.write_text(json.dumps(_now_runs("FREELANCE")), encoding="utf-8")
    monkeypatch.setattr(career_state.paths, "CAREER_MODE_RUNS", runs_file)

    _cli(["research", "--mode", "freelance", "--dry-run"])
    assert "skipped" in capsys.readouterr().out

    _cli(["research", "--mode", "freelance", "--force", "--dry-run"])
    out = capsys.readouterr().out
    assert "bypassed" in out and "DRY_RUN — mode: FREELANCE" in out
    assert set(json.loads(runs_file.read_text())) == {"FREELANCE"}  # dry run records no new run


def test_cli_research_all_modes_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(career_state.paths, "CAREER_MODE_RUNS", tmp_path / "runs.json")
    _cli(["research", "--all-modes", "--dry-run", "--limit", "20", "--region", "gulf"])
    out = capsys.readouterr().out
    assert out.count("DRY_RUN") >= 2
    assert not (tmp_path / "runs.json").exists()


def test_cli_research_without_mode_flags_is_unchanged(capsys):
    _cli(["research", "--dry-run", "--region", "gulf", "--limit", "5"])
    out = capsys.readouterr().out
    assert "DRY_RUN" in out and "mode:" not in out


# --- 19/20. backward compatibility ------------------------------------------

OLD_HEADER = ("id,date_found,source,source_url,job_title,company,country,city,region,remote,employment_type,"
              "required_experience,skills_required,software_required,project_types,visa_sponsorship,salary_min,"
              "salary_max,salary_currency,salary_period,salary_source,salary_confidence,technical,experience,software,"
              "project,location,eligibility,career_value,compensation,score,priority,recommendation,action,status,notes")


def test_pre_phase_4_2_csv_row_reads_with_safe_defaults():
    row = dict(zip(OLD_HEADER.split(","), ["old1", "2026-01-01", "TEST_FIXTURE"] + [""] * 33))
    opp = career_intelligence.opportunity_from_jobs_row(row)
    assert opp["matched_modes"] == []
    assert opp["primary_mode"] == "UNKNOWN"
    assert opp["exceptional_opportunity"] is False


def test_upsert_onto_old_csv_keeps_old_rows_and_adds_columns(tmp_path, settings):
    jobs = tmp_path / "jobs.csv"
    old_values = ["old1", "2026-01-01", "TEST_FIXTURE", "https://example.test/old", "TEST_FIXTURE Old Role",
                  "TEST_FIXTURE Old Co"] + [""] * 24 + ["70", "GOOD", "APPLY", "APPLY", "scored", ""]
    jobs.write_text(OLD_HEADER + "\n" + ",".join(old_values) + "\n", encoding="utf-8")
    daily_research.upsert_jobs_rows([_row(settings, description="Full-time.")], jobs, settings)
    rows = list(csv.DictReader(jobs.open(encoding="utf-8")))
    assert len(rows) == 2
    assert rows[0]["id"] == "old1" and rows[0]["matched_modes"] == ""
    assert "primary_mode" in rows[0]


def test_old_snapshot_opportunity_evaluates_with_defaults(settings):
    old = {"id": "snap1", "job_title": "TEST_FIXTURE Role", "company": "TEST_FIXTURE Co", "match_score": 81}
    prio.evaluate_opportunity(old, settings)
    assert old["matched_modes"] == [] and old["primary_mode"] == "UNKNOWN"
    assert old["exceptional_opportunity"] is False


def test_old_research_snapshot_without_mode_still_loads_and_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(research.paths, "DATA_RESEARCH_RUNS", tmp_path)
    old = {"run_id": "old", "started_at": "x", "completed_at": "x", "queries": {}, "status": "PARTIAL",
           "providers": {"attempted": [], "successful": [], "failed": []}, "results_count": 0,
           "new_jobs": 0, "duplicates": 0, "errors": [], "source_health": []}
    (tmp_path / "old.json").write_text(json.dumps(old), encoding="utf-8")
    runs = research.load_research_runs()
    assert runs[0]["run_id"] == "old"
    research.print_research_summary(runs[0])
    assert "Research run old" in capsys.readouterr().out


def test_real_career_state_has_the_phase_4_2_sections():
    state = career_state.load_career_state()
    assert "REMOTE_FULL_TIME" in state["search_modes"]
    assert state["exceptional"]["enabled"] is True
    assert prio.load_settings(state)["goal"] == state["current_primary_goal"]
