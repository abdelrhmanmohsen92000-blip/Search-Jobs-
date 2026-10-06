#!/usr/bin/env python3
"""Company intelligence engine.

Builds/updates a company record (schema below) and classifies it as
OPEN_VACANCY or HIDDEN_OPPORTUNITY. A company is never excluded just for
lacking a public vacancy — HIDDEN_OPPORTUNITY is a first-class category.

This module does NOT fetch data from the web itself (no live access in this
environment — see README.md). It takes company facts already gathered
(manually, or by an agent/session with browser access) as a dict and turns
them into a scored, schema-consistent record appended to tracking/companies.csv.
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

FIELDNAMES = [
    "date_found", "company_name", "country", "city", "region", "industry", "company_size",
    "website", "careers_page", "linkedin_page", "relevant_projects", "bim_activity",
    "hiring_activity", "relevant_titles", "evidence_source", "ai_fit_score", "category",
    "status", "notes",
]

DECISION_MAKER_CATEGORIES = {
    "A": "Hiring / decision-making authority",
    "B": "Strong professional connection",
    "C": "Industry network / future opportunity",
}


def compute_fit_score(company):
    """0-100 heuristic fit score from available signals (0-10 each, scaled).

    Signals: bim_activity, hiring_activity, relevant_titles presence,
    project_type overlap with profile, and international/remote friendliness.
    This is intentionally the same 0-10-scaled-up pattern as opportunity
    scoring, but lighter-weight since companies (vs. postings) have fewer
    hard requirements to compare against.
    """
    profile = cfg_lib.load_profile_skills()
    profile_projects = {p.lower() for p in profile.get("project_types", [])}

    score = 0.0
    if company.get("bim_activity"):
        score += 30
    if company.get("hiring_activity"):
        score += 25
    if company.get("relevant_titles"):
        score += 20
    projects = {p.strip().lower() for p in (company.get("relevant_projects") or "").split(",") if p.strip()}
    if projects & profile_projects:
        score += 15
    if company.get("website") or company.get("careers_page"):
        score += 10
    return round(min(score, 100), 1)


def classify(company, fit_score):
    has_open_vacancy = bool(company.get("hiring_activity")) and "vacan" in (company.get("hiring_activity") or "").lower()
    if has_open_vacancy:
        return "OPEN_VACANCY"
    if fit_score >= 50:
        return "HIDDEN_OPPORTUNITY"
    return "LOW_PRIORITY"


def build_company_record(raw):
    country = raw.get("country")
    fit_score = compute_fit_score(raw)
    record = {
        "date_found": raw.get("date_found") or _dt.date.today().isoformat(),
        "company_name": raw.get("company_name", ""),
        "country": country or "",
        "city": raw.get("city", ""),
        "region": cfg_lib.region_for_country(country),
        "industry": raw.get("industry", ""),
        "company_size": raw.get("company_size", ""),
        "website": raw.get("website", ""),
        "careers_page": raw.get("careers_page", ""),
        "linkedin_page": raw.get("linkedin_page", ""),
        "relevant_projects": raw.get("relevant_projects", ""),
        "bim_activity": raw.get("bim_activity", ""),
        "hiring_activity": raw.get("hiring_activity", ""),
        "relevant_titles": raw.get("relevant_titles", ""),
        "evidence_source": raw.get("evidence_source", ""),
        "ai_fit_score": fit_score,
        "status": raw.get("status", "new"),
        "notes": raw.get("notes", ""),
    }
    record["category"] = classify(raw, fit_score)
    return record


def add_company(raw, csv_path=None):
    csv_path = csv_path or paths.COMPANIES_CSV
    record = build_company_record(raw)
    storage.append_csv_rows(csv_path, FIELDNAMES, [record])
    return record


def load_companies(csv_path=None):
    return storage.read_csv(csv_path or paths.COMPANIES_CSV)


def hidden_opportunities(csv_path=None):
    return [c for c in load_companies(csv_path) if c.get("category") == "HIDDEN_OPPORTUNITY"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", help="Path to a JSON file with one company dict (or a list of them) to add")
    parser.add_argument("--list-hidden", action="store_true", help="List current HIDDEN_OPPORTUNITY companies")
    args = parser.parse_args()

    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        records = [data] if isinstance(data, dict) else data
        for raw in records:
            rec = add_company(raw)
            print(f"Added: {rec['company_name']} -> {rec['category']} (fit={rec['ai_fit_score']})")
    elif args.list_hidden:
        for c in hidden_opportunities():
            print(f"{c['company_name']} ({c.get('country', '?')}) fit={c.get('ai_fit_score')}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
