"""Canonical source registry view (Phase 5).

config/sources.yaml stays the single place sources are declared; this module
derives one uniform, honest record per source from it plus the code that
actually exists:

    implementation:
        ADAPTER          a scripts/sources adapter makes real requests and parses them
        CAREER_PAGES     scripts/sources/company_careers.py (JSON-LD JobPosting parser)
        SEARCH_PROVIDER  an implemented search-engine provider (scripts/web/)
        RAW_FETCH_ONLY   reachable by HTTP in principle, but no parser exists — never
                         produces opportunities; covered by the browser queue instead
        BROWSER_QUEUE    protected source: human-in-the-loop only, never fetched
        MANUAL_IMPORT    results supplied by a human (data/raw/)
        CATEGORY         a category of company sites, served by the career-page registry
        NOT_IMPLEMENTED  declared (e.g. a future search API) but no code exists

Capabilities default to false: a source only gets a capability its config
explicitly declares, which in turn must match what its adapter really does.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib  # noqa: E402

CAPABILITY_KEYS = ("keyword_filter", "employment_type", "remote_filter", "location_filter",
                   "pagination", "date_filter", "structured_data")

_ADAPTER_SOURCES = {"Remote OK", "Remotive"}
_CAREER_PAGE_SOURCE = "Official company career pages"


def source_id(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _implementation(src, bucket):
    name, access = src.get("name"), src.get("access_method")
    if bucket == "search_providers":
        return "SEARCH_PROVIDER" if src.get("implemented") else "NOT_IMPLEMENTED"
    if name in _ADAPTER_SOURCES:
        return "ADAPTER"
    if name == _CAREER_PAGE_SOURCE:
        return "CAREER_PAGES"
    if access == "BROWSER_REQUIRED":
        return "BROWSER_QUEUE"
    if access == "MANUAL":
        return "MANUAL_IMPORT"
    if bucket == "company_sources":
        return "CATEGORY"
    return "RAW_FETCH_ONLY"


def list_sources(sources=None, environ=None):
    sources = sources if sources is not None else cfg_lib.load_sources()
    environ = environ if environ is not None else os.environ
    out = []
    for bucket, items in sources.items():
        for src in items or []:
            credential_env = src.get("credential_env")
            out.append({
                "id": source_id(src.get("name")),
                "name": src.get("name"),
                "bucket": bucket,
                "type": src.get("type"),
                "access_method": src.get("access_method", "UNKNOWN"),
                "enabled": src.get("enabled") is not False,
                "implementation": _implementation(src, bucket),
                "capabilities": {k: bool((src.get("capabilities") or {}).get(k, False)) for k in CAPABILITY_KEYS},
                "credential_env": credential_env,
                "credential_present": bool(credential_env and environ.get(credential_env)),
            })
    out.append({
        "id": "manual_import", "name": "Manual Import", "bucket": "manual", "type": "manual",
        "access_method": "MANUAL", "enabled": True, "implementation": "MANUAL_IMPORT",
        "capabilities": {k: False for k in CAPABILITY_KEYS}, "credential_env": None, "credential_present": False,
    })
    return out


def get_source(name, sources=None, environ=None):
    return next((s for s in list_sources(sources, environ) if s["name"] == name or s["id"] == name), None)


def unattempted_status(src, environ=None):
    """The honest status for a configured source the pipeline did not call
    this cycle — so source health never reports silence as success."""
    environ = environ if environ is not None else os.environ
    if src.get("implementation") == "NOT_IMPLEMENTED" or src.get("implemented") is False:
        return "NOT_IMPLEMENTED"
    if src.get("credential_env") and not environ.get(src["credential_env"]):
        return "AUTH_REQUIRED"
    if src.get("enabled") is False:
        return "DISABLED"
    if src.get("access_method") == "BROWSER_REQUIRED":
        return "BROWSER_REQUIRED"
    if src.get("access_method") == "MANUAL":
        return "MANUAL"
    return "NOT_RUN_THIS_CYCLE"
