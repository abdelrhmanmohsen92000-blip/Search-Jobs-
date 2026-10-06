"""Tests for the real TAFKEEK portfolio import (config/portfolio_projects.yaml)
and the evidence-strength hierarchy in scripts/intelligence/application_strategy.py.

All fixtures are local — no network access, matching the rest of this suite.
"""
import json
from pathlib import Path

import pytest
import yaml

from scripts.intelligence.application_strategy import (
    combined_portfolio_evidence,
    match_portfolio_projects,
    match_profile_capability_evidence,
    match_regional_experience,
)

SCHEMA = json.loads(Path("schemas/portfolio_project.schema.json").read_text())
REAL_DATA = yaml.safe_load(Path("config/portfolio_projects.yaml").read_text())
REAL_PROJECTS = REAL_DATA["portfolio_projects"]
PROFILE_SKILLS = yaml.safe_load(Path("config/profile_skills.yaml").read_text())


def test_four_real_projects_validate_against_schema():
    import jsonschema

    assert len(REAL_PROJECTS) == 4
    for project in REAL_PROJECTS:
        jsonschema.validate(project, SCHEMA)


def test_real_projects_carry_source_provenance():
    for project in REAL_PROJECTS:
        assert project["source_url"] == (
            "https://abdelrhmanmohsen92000-blip.github.io/tafkeek-company-portfolio/"
        )
        assert project["source_type"] == "PORTFOLIO_WEBSITE"
        assert "evidence_status" in project


def test_top_level_source_metadata_block_exists():
    assert REAL_DATA["source"]["type"] == "PORTFOLIO_WEBSITE"
    assert REAL_DATA["source"]["url"].startswith("https://")
    assert "evidence_status" in REAL_DATA["source"]


def test_no_record_claims_verified_without_independent_fetch():
    # This session's fetch of the source site was blocked by network policy,
    # so nothing imported here may claim full VERIFIED status yet.
    assert REAL_DATA["source"]["evidence_status"] == "PARTIAL"
    for project in REAL_PROJECTS:
        assert project["evidence_status"] in ("PARTIAL", "UNKNOWN")


def test_representative_visual_status_never_defaults_to_confirmed():
    for project in REAL_PROJECTS:
        assert project["visual_evidence_status"] in ("REPRESENTATIVE", "UNKNOWN")
        assert project["visual_evidence_status"] != "CONFIRMED"


def test_unsupported_per_project_facts_remain_unknown_or_empty():
    for project in REAL_PROJECTS:
        # Never fabricated: client, budget, exact per-project software/LOD,
        # team size, drawing/clash counts, savings.
        assert project["software"] == []
        assert project["bim_level"] is None
        assert project["role"] is None


def test_profile_capabilities_kept_separate_from_project_records():
    assert "verified_capabilities" in PROFILE_SKILLS
    names = {c["name"] for c in PROFILE_SKILLS["verified_capabilities"]}
    assert "Autodesk Revit" in names
    assert "Navisworks" in names
    # No project record should carry these as its own per-project software —
    # they are profile-wide capabilities, never auto-assigned per project.
    for project in REAL_PROJECTS:
        assert "Autodesk Revit" not in (project.get("software") or [])


def test_regional_experience_kept_separate_from_project_location():
    assert "regional_experience" in PROFILE_SKILLS
    countries = {c["country"] for c in PROFILE_SKILLS["regional_experience"]}
    assert {"Egypt", "Saudi Arabia", "UAE", "Qatar"} <= countries
    # Supply Chain - Riyadh's own location is the only project explicitly
    # tied to Saudi Arabia; regional_experience must not silently attach
    # Saudi Arabia to projects whose own record doesn't say so.
    supply_chain = next(p for p in REAL_PROJECTS if p["name"] == "Supply Chain - Riyadh")
    la_mer = next(p for p in REAL_PROJECTS if p["name"] == "La-Mer Compound")
    assert "Saudi Arabia" in supply_chain["location"]
    assert la_mer["location"] is None


def test_healthcare_revit_job_combines_project_and_profile_evidence():
    opportunity = {
        "project_types": ["Healthcare"],
        "software_required": ["Autodesk Revit"],
        "skills_required": ["BIM Coordination"],
        "country": "Saudi Arabia",
    }
    evidence = combined_portfolio_evidence(opportunity)
    assert evidence != "PORTFOLIO_DATA_INSUFFICIENT"
    tiers = {e["evidence_tier"] for e in evidence}
    assert "DIRECT_PROJECT_EVIDENCE" in tiers
    assert "PROFILE_CAPABILITY" in tiers
    assert "REGIONAL_EXPERIENCE" in tiers
    # Direct project evidence must rank ahead of generic capability evidence.
    assert evidence[0]["evidence_tier"] == "DIRECT_PROJECT_EVIDENCE"
    project_names = {e.get("project") for e in evidence if "project" in e}
    assert "Supply Chain - Riyadh" in project_names


def test_villa_interior_job_never_cites_unrelated_healthcare_project():
    opportunity = {
        "project_types": ["Luxury Villas", "Residential"],
        "software_required": [],
        "skills_required": ["Interior Design"],
        "country": "Egypt",
    }
    evidence = combined_portfolio_evidence(opportunity)
    assert evidence != "PORTFOLIO_DATA_INSUFFICIENT"
    project_names = {e.get("project") for e in evidence if "project" in e}
    assert "Supply Chain - Riyadh" not in project_names
    assert "Private Residential Interiors" in project_names


def test_direct_project_evidence_outranks_profile_capability_in_ranking():
    opportunity = {
        "project_types": ["Healthcare"],
        "software_required": ["Autodesk Revit"],
        "skills_required": [],
        "country": None,
    }
    evidence = combined_portfolio_evidence(opportunity)
    tier_order = [e["evidence_tier"] for e in evidence]
    # DIRECT_PROJECT_EVIDENCE entries must never appear after a
    # PROFILE_CAPABILITY entry in the ranked list.
    if "DIRECT_PROJECT_EVIDENCE" in tier_order and "PROFILE_CAPABILITY" in tier_order:
        assert tier_order.index("DIRECT_PROJECT_EVIDENCE") < tier_order.index("PROFILE_CAPABILITY")


def test_profile_capability_evidence_ignores_unmatched_opportunity():
    opportunity = {"software_required": ["Unreal Engine"], "skills_required": []}
    assert match_profile_capability_evidence(opportunity) == []


def test_regional_evidence_ignores_unmatched_country():
    opportunity = {"country": "Germany"}
    assert match_regional_experience(opportunity) == []


def test_portfolio_matching_still_reports_insufficient_with_explicit_empty_profile():
    assert match_portfolio_projects({"project_types": ["Residential"]}, profile={}) == (
        "PORTFOLIO_DATA_INSUFFICIENT"
    )
    assert combined_portfolio_evidence({"project_types": ["Residential"]}, profile={}) == (
        "PORTFOLIO_DATA_INSUFFICIENT"
    )


def test_combined_evidence_insufficient_when_truly_no_overlap():
    opportunity = {
        "project_types": ["Marine Engineering"],
        "software_required": ["SolidWorks"],
        "skills_required": [],
        "country": "Brazil",
    }
    assert combined_portfolio_evidence(opportunity) == "PORTFOLIO_DATA_INSUFFICIENT"


def test_portfolio_projects_config_loader_merges_real_data():
    from scripts.lib import config as cfg_lib

    cfg_lib.load_profile_skills.cache_clear()
    cfg_lib.load_portfolio_projects.cache_clear()
    profile = cfg_lib.load_profile_skills()
    names = {p["name"] for p in profile["portfolio_projects"]}
    assert {"Square Business Hub", "La-Mer Compound", "Supply Chain - Riyadh", "Private Residential Interiors"} <= names
    assert profile["portfolio_source"]["type"] == "PORTFOLIO_WEBSITE"
