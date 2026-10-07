"""Runtime environment settings (V1.3 hardening).

NETWORK_MODE controls whether Career Hunter makes live HTTP requests:
    local    (default) — normal operation on a workstation; live sources are requested.
    cloud    — same behaviour; documents that the run is in a cloud container, whose
               egress policy must allow the job/career hosts (see docs/SETUP.md).
    offline  — no live request is ever made. Live sources are reported OFFLINE
               (not attempted, so no failure/cooldown is recorded); manual import,
               analysis, reports, dashboard and learning all keep working.

Every optional credential is read from the environment only (never a file).
"""
import os

NETWORK_MODES = ("local", "cloud", "offline")

ENVIRONMENT_VARIABLES = {
    "NETWORK_MODE": "local | cloud | offline (default local).",
    "CAREER_HUNTER_WORKSPACE": "Directory for tracking/, data/, reports/ (default: the repository).",
    "BRAVE_SEARCH_API_KEY": "Optional. Enables Brave Search discovery; without it search is AUTH_REQUIRED.",
    "ANTHROPIC_API_KEY": "Optional. Enables LLM enrichment when config/ai.yaml provider is 'claude'.",
    "ANTHROPIC_MODEL": "Optional. Overrides the Claude model configured in config/ai.yaml.",
    "CAREER_HUNTER_WEBHOOK_URL": "Optional. If set, webhook notifications are POSTed here (else only written to the outbox).",
    "CAREER_HUNTER_TIMEZONE": "Optional. Overrides config/schedules.yaml timezone (default Africa/Cairo).",
}


def network_mode():
    mode = (os.environ.get("NETWORK_MODE") or "local").strip().lower()
    return mode if mode in NETWORK_MODES else "local"


def is_offline():
    return network_mode() == "offline"


def environment_status():
    """Which variables are set — values are never returned or printed."""
    return {name: ("set" if os.environ.get(name) else "not set") for name in ENVIRONMENT_VARIABLES}
