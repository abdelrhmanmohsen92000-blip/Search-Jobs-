"""Persistent, cross-run source health tracking (Phase 3).

scripts/sources/base.SourceRunResult already reports an honest per-call
status; this module accumulates that into a durable history so the user can
see degradation/recovery over time, not just the last run:
    AVAILABLE    - reached and returned usable data (or a legitimate empty result)
    DEGRADED     - reached, but something went wrong extracting/parsing
    UNAVAILABLE  - could not be reached this run (network/timeout/non-200)
    BLOCKED      - reached the proxy/edge but was explicitly denied (403/
                   connect_rejected) — distinct from a transient UNAVAILABLE
    MANUAL       - never auto-run; human-in-the-loop by design (BROWSER_REQUIRED,
                   NOT_IMPLEMENTED, DISABLED)

Never hides a failure: every update is appended to tracking/source_health.csv
(via the existing backup-on-write storage helper), so a run of all-UNAVAILABLE
sources is just as visible in history as a run of all-AVAILABLE ones.
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402

FIELDNAMES = [
    "source", "status", "last_success", "last_failure", "error_type",
    "request_count", "success_count", "updated_at",
]

_BLOCKED_MARKERS = ("403", "connect_rejected", "forbidden")

_STATUS_MAP = {
    "SUCCESS": "AVAILABLE",
    "EMPTY": "AVAILABLE",
    "FETCHED_UNPARSED": "DEGRADED",
    "ERROR": "DEGRADED",
    "PARSE_ERROR": "DEGRADED",
    "UNAVAILABLE": "UNAVAILABLE",
    "BROWSER_REQUIRED": "MANUAL",
    "NOT_IMPLEMENTED": "MANUAL",
    "DISABLED": "MANUAL",
    "MANUAL": "MANUAL",
    "NOT_RUN_THIS_CYCLE": "MANUAL",  # never actually attempted this run — not a failure
}


def classify_status(raw_status, error=None):
    """Maps a SourceRunResult.status (+ its error text) to the 5-state model.
    UNAVAILABLE is upgraded to BLOCKED when the error text itself says the
    request was actively denied, rather than merely timing out/failing —
    these mean different things to someone deciding whether to retry.
    """
    mapped = _STATUS_MAP.get(raw_status, "UNAVAILABLE")
    if mapped == "UNAVAILABLE" and error and any(marker in error.lower() for marker in _BLOCKED_MARKERS):
        return "BLOCKED"
    return mapped


def load_health(csv_path=None):
    rows = storage.read_csv(csv_path or paths.SOURCE_HEALTH_CSV)
    return {r["source"]: r for r in rows if r.get("source")}


def record_result(source_name, raw_status, error=None, existing=None, now=None):
    """Pure function: given the current health row for a source (or None for
    a never-seen source) and a new result, returns the updated row. Kept
    separate from file I/O so it's trivially testable.
    """
    now = now or _dt.datetime.now().isoformat(timespec="seconds")
    existing = existing or {}
    status = classify_status(raw_status, error)

    request_count = int(existing.get("request_count") or 0) + 1
    success_count = int(existing.get("success_count") or 0) + (1 if status == "AVAILABLE" else 0)

    row = {
        "source": source_name,
        "status": status,
        "last_success": now if status == "AVAILABLE" else (existing.get("last_success") or ""),
        "last_failure": now if status in ("DEGRADED", "UNAVAILABLE", "BLOCKED") else (existing.get("last_failure") or ""),
        "error_type": (error or "") if status in ("DEGRADED", "UNAVAILABLE", "BLOCKED") else "",
        "request_count": request_count,
        "success_count": success_count,
        "updated_at": now,
    }
    return row


def update_source_health(source_health_results, csv_path=None):
    """source_health_results: iterable of dicts with at least {source, status,
    error} — the same shape scripts.daily_research.run_source_adapters()
    already produces. MANUAL-mapped sources still get a row (so they're
    visible), but never count as a request/failure against the source.

    Returns the full updated {source: row} map.
    """
    csv_path = csv_path or paths.SOURCE_HEALTH_CSV
    existing = load_health(csv_path)

    for result in source_health_results:
        source_name = result.get("source")
        if not source_name:
            continue
        raw_status = result.get("status")
        mapped = classify_status(raw_status, result.get("error"))
        if mapped == "MANUAL":
            # Record its presence/current state without inflating request/success counters —
            # a BROWSER_REQUIRED source isn't "attempted and failed", it's "not auto-run by design".
            row = {**existing.get(source_name, {}), "source": source_name, "status": "MANUAL",
                   "updated_at": _dt.datetime.now().isoformat(timespec="seconds")}
            for field in FIELDNAMES:
                row.setdefault(field, "")
        else:
            row = record_result(source_name, raw_status, result.get("error"), existing.get(source_name))
        existing[source_name] = row

    storage.write_csv(csv_path, FIELDNAMES, list(existing.values()))
    return existing
