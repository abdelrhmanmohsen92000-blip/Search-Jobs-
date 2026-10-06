"""Company analyzer (V1.4).

Builds on scripts/company_intelligence.py (V1.2 — OPEN_VACANCY /
HIDDEN_OPPORTUNITY / LOW_PRIORITY classification, ai_fit_score) without
duplicating its scoring. Adds a letter COMPANY_PRIORITY grade and a fuller,
honestly-gapped company analysis: every dimension this system has no real
evidence for (market reputation, international activity, ...) reports
UNKNOWN rather than a guess.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402

PRIORITY_BANDS = [(85, "A+"), (70, "A"), (50, "B"), (30, "C"), (0, "D")]


def company_priority(fit_score):
    fit_score = fit_score or 0
    for threshold, label in PRIORITY_BANDS:
        if fit_score >= threshold:
            return label
    return "D"


def _bool_evidence(value):
    return bool(value and str(value).strip())


def _likely_hiring_managers(company_name, contacts=None):
    """Cross-references tracking/networking.csv (and tracking/contacts.csv)
    for people already logged against this company. Returns [] rather than
    inventing a name when none has been researched yet.
    """
    contacts = contacts if contacts is not None else storage.read_csv(paths.NETWORKING_CSV)
    name_lower = (company_name or "").strip().lower()
    return [c["person"] for c in contacts if (c.get("company") or "").strip().lower() == name_lower and c.get("person")]


def analyze_company(company_record, contacts=None):
    """company_record: a row from tracking/companies.csv (or an equivalent
    dict). Returns the full V1.4 company analysis.
    """
    fit_score = float(company_record.get("ai_fit_score") or 0)
    hiring_managers = _likely_hiring_managers(company_record.get("company_name"), contacts)

    hiring_activity = company_record.get("hiring_activity") or "UNKNOWN"
    bim_maturity = "EVIDENCED" if _bool_evidence(company_record.get("bim_activity")) else "UNKNOWN"
    architecture_activity = company_record.get("relevant_projects") or "UNKNOWN"
    project_quality = "UNKNOWN"  # no objective evidence source for this yet — never guessed
    market_reputation = "UNKNOWN"  # same — would need a real review/ranking source
    growth_signals = []
    if _bool_evidence(company_record.get("hiring_activity")):
        growth_signals.append("Active hiring activity logged.")
    if _bool_evidence(company_record.get("bim_activity")):
        growth_signals.append("BIM activity/expansion signal logged.")
    international_activity = "UNKNOWN"
    relevant_departments = company_record.get("relevant_titles") or "UNKNOWN"
    potential_hidden_opportunity = company_record.get("category") == "HIDDEN_OPPORTUNITY"

    recommended_networking_action = (
        "NETWORK_FIRST — no confirmed vacancy, but hiring/BIM signal is present; identify and approach a decision-maker."
        if potential_hidden_opportunity else
        "Monitor — insufficient signal yet to justify proactive networking." if fit_score < 50 else
        "Apply through the standard channel; networking is supplementary here."
    )

    return {
        "company_name": company_record.get("company_name"),
        "company_fit_score": fit_score,
        "company_priority": company_priority(fit_score),
        "hiring_activity": hiring_activity,
        "bim_maturity": bim_maturity,
        "architecture_activity": architecture_activity,
        "project_quality": project_quality,
        "market_reputation": market_reputation,
        "growth_signals": growth_signals or ["UNKNOWN — no growth signal logged yet."],
        "international_activity": international_activity,
        "relevant_departments": relevant_departments,
        "likely_hiring_managers": hiring_managers or ["DATA_INSUFFICIENT — no contacts researched yet for this company."],
        "potential_hidden_opportunity": potential_hidden_opportunity,
        "recommended_networking_action": recommended_networking_action,
    }
