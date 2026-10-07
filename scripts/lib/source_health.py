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
from scripts.lib.error_types import classify_error  # noqa: E402

FIELDNAMES = [
    "source", "status", "last_success", "last_failure", "error_type", "error_detail",
    "request_count", "success_count", "consecutive_failures", "updated_at",
    # Phase 5 — appended so older rows/readers keep working.
    "health_state", "last_attempt", "http_status", "last_result_count", "cooldown_until",
]

# Phase 5 user-facing health vocabulary (`health_state`), next to the
# original 5-state `status` which is kept unchanged for compatibility:
#   VERIFIED         live request succeeded (data or a genuine empty result)
#   PARTIAL          reached, but nothing could be extracted (e.g. no parser output)
#   BLOCKED          actively refused (HTTP 403, proxy refused the tunnel)
#   AUTH_REQUIRED    needs credentials that are not configured (HTTP 401 / missing key)
#   BROWSER_REQUIRED protected source — human-in-the-loop browser queue only
#   PARSER_FAILED    response received but could not be parsed
#   RATE_LIMITED     HTTP 429 / explicit rate limit
#   UNAVAILABLE      transient: timeout, DNS, 5xx
#   UNKNOWN          never attempted
HEALTH_STATES = ("VERIFIED", "PARTIAL", "BLOCKED", "AUTH_REQUIRED", "BROWSER_REQUIRED",
                 "PARSER_FAILED", "RATE_LIMITED", "UNAVAILABLE", "UNKNOWN")

# Used only when config/search_matrix.yaml has no `source_policy` section.
FALLBACK_POLICY = {
    "cooldown_minutes": {"BLOCKED": 1440, "AUTH_REQUIRED": 1440, "RATE_LIMITED": 60,
                         "PARSER_FAILED": 360, "UNAVAILABLE": 15},
    "max_cooldown_minutes": 1440,
}

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
    "AUTH_REQUIRED": "MANUAL",  # credentials missing — never attempted, so not a failed request
    "COOLDOWN": "MANUAL",  # skipped on purpose during a backoff window — not a failed request
    "OFFLINE": "MANUAL",  # NETWORK_MODE=offline — deliberately not requested
}

_NOT_ATTEMPTED = ("NOT_RUN_THIS_CYCLE", "DISABLED", "NOT_IMPLEMENTED", "MANUAL", "COOLDOWN", "OFFLINE")


def load_policy(matrix=None):
    from scripts.lib import config as cfg_lib
    matrix = matrix if matrix is not None else cfg_lib.load_search_matrix()
    policy = matrix.get("source_policy") or {}
    return {
        "cooldown_minutes": {**FALLBACK_POLICY["cooldown_minutes"], **(policy.get("cooldown_minutes") or {})},
        "max_cooldown_minutes": policy.get("max_cooldown_minutes", FALLBACK_POLICY["max_cooldown_minutes"]),
    }


def derive_health_state(raw_status, status, error_type, previous=None):
    """Maps one attempt onto the Phase 5 HEALTH_STATES vocabulary."""
    if raw_status == "BROWSER_REQUIRED":
        return "BROWSER_REQUIRED"
    if raw_status == "AUTH_REQUIRED" or error_type in ("AUTH_REQUIRED", "HTTP_401"):
        return "AUTH_REQUIRED"
    if raw_status in _NOT_ATTEMPTED:
        return previous or "UNKNOWN"
    if status == "AVAILABLE":
        return "VERIFIED"
    if error_type == "RATE_LIMITED":
        return "RATE_LIMITED"
    if status == "BLOCKED" or error_type == "HTTP_403":
        return "BLOCKED"
    if error_type in ("PARSER_ERROR", "INVALID_RESPONSE"):
        return "PARSER_FAILED"
    if status == "DEGRADED":
        return "PARTIAL"
    return "UNAVAILABLE"


def cooldown_minutes(health_state, consecutive_failures, policy=None):
    """Backoff window after a failure. Transient UNAVAILABLE failures back off
    exponentially; every window is capped, so no source is ever removed for
    good — it is simply re-checked once the window passes (Phase 5 §30)."""
    policy = policy or load_policy()
    base = policy["cooldown_minutes"].get(health_state)
    if not base:
        return 0
    if health_state == "UNAVAILABLE":
        base = base * (2 ** max(0, consecutive_failures - 1))
    return min(base, policy["max_cooldown_minutes"])


def in_cooldown(row, now=None):
    until = (row or {}).get("cooldown_until")
    if not until:
        return False
    now = now or _dt.datetime.now()
    try:
        return _dt.datetime.fromisoformat(until) > now
    except ValueError:
        return False


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


def record_result(source_name, raw_status, error=None, existing=None, now=None, http_status=None,
                  result_count=None, policy=None):
    """Pure function: given the current health row for a source (or None for
    a never-seen source) and a new result, returns the updated row. Kept
    separate from file I/O so it's trivially testable.
    """
    now = now or _dt.datetime.now().isoformat(timespec="seconds")
    existing = existing or {}
    status = classify_status(raw_status, error)

    request_count = int(existing.get("request_count") or 0) + 1
    success_count = int(existing.get("success_count") or 0) + (1 if status == "AVAILABLE" else 0)
    is_failure = status in ("DEGRADED", "UNAVAILABLE", "BLOCKED")
    consecutive_failures = (int(existing.get("consecutive_failures") or 0) + 1) if is_failure else 0
    error_type = (classify_error(raw_status, error) or "") if is_failure else ""
    if http_status == 429:
        error_type = "RATE_LIMITED"
    health_state = derive_health_state(raw_status, status, error_type, existing.get("health_state"))

    cooldown_until = ""
    if is_failure:
        minutes = cooldown_minutes(health_state, consecutive_failures, policy)
        if minutes:
            cooldown_until = (_dt.datetime.fromisoformat(now) + _dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")

    row = {
        "source": source_name,
        "status": status,
        "last_success": now if status == "AVAILABLE" else (existing.get("last_success") or ""),
        "last_failure": now if is_failure else (existing.get("last_failure") or ""),
        "error_type": error_type,
        "error_detail": (error or "") if is_failure else "",
        "request_count": request_count,
        "success_count": success_count,
        "consecutive_failures": consecutive_failures,
        "updated_at": now,
        "health_state": health_state,
        "last_attempt": now,
        "http_status": http_status if http_status is not None else "",
        "last_result_count": result_count if result_count is not None else "",
        "cooldown_until": cooldown_until,
    }
    return row


def source_priority(row):
    """Routing priority (Phase 4 §SOURCE HEALTH) derived from a source's own
    recorded health — never a one-strike judgment: a source only drops to LOW
    after repeated consecutive failures, and AUTH_REQUIRED is its own signal
    (credentials missing, not a flaky network) rather than a generic failure.

    Returns one of HIGH / MEDIUM / LOW / DISABLED.
    """
    status = row.get("status")
    if status == "MANUAL":
        return "MEDIUM"  # browser-required/disabled-by-design — routed to the browser queue, not auto-skipped
    if row.get("error_type") == "AUTH_REQUIRED":
        return "DISABLED"
    consecutive_failures = int(row.get("consecutive_failures") or 0)
    if status == "AVAILABLE" and consecutive_failures == 0:
        return "HIGH"
    if consecutive_failures >= 5:
        return "LOW"
    if status in ("UNAVAILABLE", "BLOCKED", "DEGRADED"):
        return "MEDIUM"
    return "MEDIUM"


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
        previous = existing.get(source_name, {})
        if raw_status in ("COOLDOWN", "OFFLINE") and previous:
            continue  # skipped during its backoff window: the last real outcome stands unchanged
        if mapped == "MANUAL":
            # Record its presence/current state without inflating request/success counters —
            # a BROWSER_REQUIRED source isn't "attempted and failed", it's "not auto-run by design".
            row = {**previous, "source": source_name, "status": "MANUAL",
                   "updated_at": _dt.datetime.now().isoformat(timespec="seconds")}
            for field in FIELDNAMES:
                row.setdefault(field, "")
            row["health_state"] = derive_health_state(raw_status, "MANUAL", "", previous.get("health_state"))
            if raw_status == "AUTH_REQUIRED":
                row["error_type"], row["error_detail"] = "AUTH_REQUIRED", result.get("error") or ""
        else:
            row = record_result(source_name, raw_status, result.get("error"), previous,
                                http_status=result.get("http_status"),
                                result_count=len(result.get("opportunities") or []) or result.get("raw_count"))
        existing[source_name] = row

    storage.write_csv(csv_path, FIELDNAMES, list(existing.values()))
    return existing
