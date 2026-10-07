"""Central path constants so every script agrees on repo layout.

Configuration always comes from the repository's config/ directory. Mutable
data (tracking/, data/, reports/) lives in a *workspace*: the repository
itself by default, or an isolated directory chosen with the
CAREER_HUNTER_WORKSPACE environment variable / `career_hunter.py --workspace`
(used e.g. by the synthetic demo so demo data can never reach the real
trackers). Callers must read these as `paths.X` at call time, never copy them
at import time, so a workspace switch takes effect everywhere.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = ROOT / "config"
SCHEMAS_DIR = ROOT / "schemas"
PROFILE_SKILLS = CONFIG_DIR / "profile_skills.yaml"
PORTFOLIO_PROJECTS = CONFIG_DIR / "portfolio_projects.yaml"
CAREER_STATE = CONFIG_DIR / "career_state.yaml"
SEARCH_MATRIX = CONFIG_DIR / "search_matrix.yaml"
SOURCES = CONFIG_DIR / "sources.yaml"
AI_CONFIG = CONFIG_DIR / "ai.yaml"
OPPORTUNITY_SCHEMA = SCHEMAS_DIR / "opportunity.schema.json"

TRACKER_FILES = {
    "JOBS_CSV": "jobs.csv", "COMPANIES_CSV": "companies.csv", "CONTACTS_CSV": "contacts.csv",
    "APPLICATIONS_CSV": "applications.csv", "NETWORKING_CSV": "networking.csv", "DECISIONS_CSV": "decisions.csv",
    "SKILL_GAPS_CSV": "skill_gaps.csv", "LEARNING_CSV": "learning.csv", "ALERTS_CSV": "alerts.csv",
    "SOURCE_HEALTH_CSV": "source_health.csv", "COMPANY_CAREER_PAGES_CSV": "company_career_pages.csv",
    # V1.4-V1.7 entities
    "ANALYSES_CSV": "analyses.csv", "APPLICATION_EVENTS_CSV": "application_events.csv",
    "NETWORKING_ACTIONS_CSV": "networking_actions.csv", "FEEDBACK_CSV": "feedback.csv",
    "NOTIFICATIONS_CSV": "notifications.csv",
}

WORKSPACE = ROOT


def use_workspace(root=None):
    """Point every mutable path at `root` (default: the repository). Returns the
    resolved workspace root."""
    global WORKSPACE, TRACKING_DIR, DATA_DIR, DATA_RAW, DATA_PROCESSED, DATA_ARCHIVE, DATA_ALERTS
    global REPORTS_DIR, DATA_RESEARCH_RUNS, CAREER_MODE_RUNS, SCHEDULE_STATE, OUTBOX_DIR, LEARNING_DIR
    WORKSPACE = Path(root).resolve() if root else ROOT
    TRACKING_DIR = WORKSPACE / "tracking"
    DATA_DIR = WORKSPACE / "data"
    DATA_RAW = DATA_DIR / "raw"
    DATA_PROCESSED = DATA_DIR / "processed"
    DATA_ARCHIVE = DATA_DIR / "archive"
    DATA_ALERTS = DATA_DIR / "alerts"
    DATA_RESEARCH_RUNS = DATA_DIR / "research_runs"
    CAREER_MODE_RUNS = DATA_DIR / "career_mode_runs.json"
    SCHEDULE_STATE = DATA_DIR / "schedule_state.json"
    OUTBOX_DIR = DATA_DIR / "outbox"
    LEARNING_DIR = DATA_DIR / "learning"
    REPORTS_DIR = WORKSPACE / "reports"
    for attr, filename in TRACKER_FILES.items():
        globals()[attr] = TRACKING_DIR / filename
    return WORKSPACE


use_workspace(os.environ.get("CAREER_HUNTER_WORKSPACE") or None)
