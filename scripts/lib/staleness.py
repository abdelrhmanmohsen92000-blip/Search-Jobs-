"""Stale opportunity detection.

Lifecycle states: NEW, ACTIVE, STALE, CLOSED, UNCERTAIN. Rules are
deliberately conservative — CLOSED is only ever returned when the record
carries explicit evidence (a closed/filled marker in description or
risk_flags), never inferred purely from age. Age-based staleness is
configurable via `stale_after_days` / `new_within_days`.
"""
import datetime as _dt

CLOSED_MARKERS = ("position filled", "no longer accepting", "job closed", "vacancy closed", "position has been filled")


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
