"""Stale opportunity detection.

Lifecycle states: NEW, ACTIVE, STALE, CLOSED, UNCERTAIN. Rules are
deliberately conservative — CLOSED is only ever returned when the record
carries explicit evidence (a closed/filled marker in description or
risk_flags), never inferred purely from age. Age-based staleness is
configurable via `stale_after_days` / `new_within_days`.
"""
import datetime as _dt

CLOSED_MARKERS = ("position filled", "no longer accepting", "job closed", "vacancy closed", "position has been filled",
                  "job no longer available", "job is no longer available", "applications closed",
                  "position closed")

FRESHNESS_DAYS = {"FRESH": 3, "RECENT": 14, "AGING": 30}


def _parse_date(value):
    if not value:
        return None
    for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m-%dT%H:%M:%S", 19)):
        try:
            return _dt.datetime.strptime(value[:length], fmt)
        except (ValueError, TypeError):
            continue
    return None


def compute_lifecycle_status(opportunity, now=None, new_within_days=3, stale_after_days=30):
    """opportunity: a normalized opportunity dict (date_posted/date_found,
    description, risk_flags). Returns one of NEW/ACTIVE/STALE/CLOSED/UNCERTAIN.
    """
    now = now or _dt.datetime.now()

    text = " ".join(filter(None, [opportunity.get("description"), opportunity.get("reason")])).lower()
    if any(marker in text for marker in CLOSED_MARKERS):
        return "CLOSED"
    if any("closed" in (flag or "").lower() for flag in (opportunity.get("risk_flags") or [])):
        return "CLOSED"

    reference_date = _parse_date(opportunity.get("date_posted")) or _parse_date(opportunity.get("date_found"))
    if reference_date is None:
        return "UNCERTAIN"

    age_days = (now - reference_date).days
    if age_days < 0:
        return "UNCERTAIN"
    if age_days <= new_within_days:
        return "NEW"
    if age_days <= stale_after_days:
        return "ACTIVE"
    return "STALE"


def compute_freshness(opportunity, now=None, thresholds=None):
    """Phase 5 freshness: FRESH / RECENT / AGING / STALE / CLOSED / UNKNOWN.

    Unlike compute_lifecycle_status(), this uses ONLY the date the posting
    itself published (date_posted) — the date we happened to find it says
    nothing about how old the vacancy is, so with no published date the
    answer is UNKNOWN, never a guess. CLOSED needs the same explicit evidence
    as the lifecycle status.
    """
    thresholds = thresholds or FRESHNESS_DAYS
    if compute_lifecycle_status(opportunity, now=now) == "CLOSED":
        return "CLOSED"
    posted = _parse_date(opportunity.get("date_posted"))
    if posted is None:
        return "UNKNOWN"
    age_days = ((now or _dt.datetime.now()) - posted).days
    if age_days < 0:
        return "UNKNOWN"
    for label in ("FRESH", "RECENT", "AGING"):
        if age_days <= thresholds[label]:
            return label
    return "STALE"
