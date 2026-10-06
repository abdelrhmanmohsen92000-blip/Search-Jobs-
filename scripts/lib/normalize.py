"""Normalize raw, loosely-shaped opportunity dicts into the schema in
schemas/opportunity.schema.json, and validate the result.
"""
import datetime as _dt
import json

from jsonschema import Draft7Validator

from . import config as cfg_lib
from . import paths

_SCHEMA = None


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        with open(paths.OPPORTUNITY_SCHEMA, "r", encoding="utf-8") as f:
            _SCHEMA = json.load(f)
    return _SCHEMA


def _bool_or_none(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "y", "1"):
            return True
        if v in ("false", "no", "n", "0"):
            return False
    return None


def _list_or_empty(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def normalize_opportunity(raw):
    """raw: a dict with any subset of the schema's field names (loosely typed).

    Returns a fully-shaped dict matching opportunity.schema.json, with safe
    defaults for anything missing. Does not invent factual content (company,
    title, etc.) — those must be present in `raw` or will be left as given
    (empty string triggers validation failure, which is intentional: we do
    not silently fabricate a company/title).
    """
    country = raw.get("country")
    region = raw.get("region") or cfg_lib.region_for_country(country)

    normalized = {
        "id": raw.get("id") or "",
        "source": raw.get("source") or "unknown",
        "source_url": raw.get("source_url"),
        "date_found": raw.get("date_found") or _dt.date.today().isoformat(),
        "date_posted": raw.get("date_posted"),
        "company": raw.get("company") or "",
        "job_title": raw.get("job_title") or raw.get("title") or "",
        "country": country,
        "city": raw.get("city"),
        "region": region,
        "remote": _bool_or_none(raw.get("remote")),
        "employment_type": raw.get("employment_type"),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_currency": raw.get("salary_currency"),
        "experience_required": raw.get("experience_required"),
        "skills_required": _list_or_empty(raw.get("skills_required")),
        "software_required": _list_or_empty(raw.get("software_required")),
        "project_types": _list_or_empty(raw.get("project_types")),
        "visa_sponsorship": _bool_or_none(raw.get("visa_sponsorship")),
        "work_authorization": raw.get("work_authorization"),
        "description": raw.get("description"),
        "match_score": raw.get("match_score"),
        "priority": raw.get("priority"),
        "status": raw.get("status") or "new",
        "reason": raw.get("reason"),
        "risk_flags": _list_or_empty(raw.get("risk_flags")),
    }

    if "_sub_scores" in raw:
        normalized["_sub_scores"] = raw["_sub_scores"]

    from . import dedup as dedup_lib  # local import to avoid a cycle

    if not normalized["id"]:
        normalized["id"] = dedup_lib.make_id(
            normalized["company"], normalized["job_title"], normalized["city"] or normalized["country"],
            normalized["source_url"],
        )

    return normalized


def validate_opportunity(opportunity):
    """Returns a list of validation error messages (empty list = valid)."""
    validator = Draft7Validator(_schema())
    return [e.message for e in validator.iter_errors(opportunity)]
