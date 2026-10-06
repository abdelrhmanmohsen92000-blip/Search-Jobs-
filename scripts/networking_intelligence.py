#!/usr/bin/env python3
"""Networking intelligence engine.

Computes network_value_score (0-100) for a potential contact and maintains
tracking/networking.csv. Generates reports/networking_queue.md: a queue of
WHO / WHY / WHAT TO SAY / WHEN / LINK for Abdelrhman to action manually.

Hard constraint: this module NEVER sends a LinkedIn connection request or
message, never scrapes LinkedIn at scale, and never automates any account
action. It only drafts and queues. See docs/decision-makers.md.
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

FIELDNAMES = [
    "person", "role", "company", "country", "profile_url", "why_relevant",
    "network_value_score", "priority", "connection_status", "message_status",
    "last_contact", "next_followup", "notes",
]

ROLE_AUTHORITY = {
    "founder": 10, "managing director": 10, "md": 10,
    "bim director": 9, "design director": 9, "architecture director": 9, "technical director": 9,
    "bim manager": 8, "bim lead": 8, "project director": 8,
    "talent acquisition": 8, "recruiter": 7, "recruitment manager": 7, "hr manager": 6,
    "department head": 7, "senior architect": 5,
}

PRIORITY_BANDS = [(80, "A"), (55, "B"), (0, "C")]


def _role_authority_score(role):
    role_l = (role or "").strip().lower()
    for key, val in ROLE_AUTHORITY.items():
        if key in role_l:
            return val
    return 3  # unknown role: modest default


def compute_network_value_score(contact, company_fit_score=None):
    """Factors (0-10 each unless noted), scaled to 0-100:
        hiring_authority      (role-based, see ROLE_AUTHORITY)   weight 40%
        bim_architecture_relevance (0-10 input)                  weight 20%
        company_fit (0-100 from company_intelligence, /10)       weight 20%
        geographic_relevance (0-10 input)                        weight 10%
        career_value_potential (0-10 input)                      weight 10%
    """
    hiring_authority = _role_authority_score(contact.get("role"))
    bim_relevance = float(contact.get("bim_architecture_relevance", 5))
    company_fit = (company_fit_score if company_fit_score is not None else float(contact.get("company_fit_score", 50))) / 10
    geo_relevance = float(contact.get("geographic_relevance", 5))
    career_value = float(contact.get("career_value_potential", 5))

    score = (
        (hiring_authority / 10) * 40
        + (bim_relevance / 10) * 20
        + (company_fit / 10) * 20
        + (geo_relevance / 10) * 10
        + (career_value / 10) * 10
    )
    return round(score, 1)


def priority_for_score(score):
    for threshold, label in PRIORITY_BANDS:
        if score >= threshold:
            return label
    return "C"


def build_networking_record(raw, company_fit_score=None):
    score = compute_network_value_score(raw, company_fit_score)
    return {
        "person": raw.get("person", ""),
        "role": raw.get("role", ""),
        "company": raw.get("company", ""),
        "country": raw.get("country", ""),
        "profile_url": raw.get("profile_url", ""),
        "why_relevant": raw.get("why_relevant", ""),
        "network_value_score": score,
        "priority": priority_for_score(score),
        "connection_status": raw.get("connection_status", "not_connected"),
        "message_status": raw.get("message_status", "not_drafted"),
        "last_contact": raw.get("last_contact", ""),
        "next_followup": raw.get("next_followup", ""),
        "notes": raw.get("notes", ""),
    }


def add_contact(raw, company_fit_score=None, csv_path=None):
    csv_path = csv_path or paths.NETWORKING_CSV
    record = build_networking_record(raw, company_fit_score)
    storage.append_csv_rows(csv_path, FIELDNAMES, [record])
    return record


def load_networking(csv_path=None):
    return storage.read_csv(csv_path or paths.NETWORKING_CSV)


def draft_talking_points(record):
    return (
        f"Reference {record['company']}'s recent BIM/architecture activity or a specific "
        f"project; introduce 4+ years BIM/Revit experience; ask about {record['role']} "
        f"perspective on {record['company']}'s BIM workflow or open roles."
    )


def generate_networking_queue(csv_path=None, out_path=None):
    out_path = out_path or (paths.REPORTS_DIR / "networking_queue.md")
    contacts = load_networking(csv_path)
    contacts_sorted = sorted(contacts, key=lambda c: float(c.get("network_value_score") or 0), reverse=True)

    lines = [
        "# Networking Queue",
        "",
        f"_Generated: {_dt.date.today().isoformat()}_",
        "",
        "All connection requests and messages below are DRAFTS ONLY. ",
        "Abdelrhman reviews and sends every LinkedIn action manually — nothing here is automated.",
        "",
    ]
    if not contacts_sorted:
        lines.append("_No contacts in tracking/networking.csv yet. Add candidates via "
                      "`python3 career_hunter.py networking --from-json <file>`._")
    for c in contacts_sorted:
        lines.extend([
            f"## {c.get('person') or '(name unknown)'} — {c.get('role', '')} at {c.get('company', '')}",
            f"- **Priority:** {c.get('priority', '')} (score {c.get('network_value_score', '')})",
            f"- **WHO:** {c.get('person', '')}, {c.get('role', '')}, {c.get('company', '')} ({c.get('country', '')})",
            f"- **WHY:** {c.get('why_relevant', '') or 'See company record for BIM/hiring signals.'}",
            f"- **WHAT TO SAY:** {draft_talking_points(c)}",
            f"- **WHEN:** {c.get('next_followup') or 'Next available networking session'}",
            f"- **LINK:** {c.get('profile_url', '') or '(not recorded)'}",
            f"- **Status:** connection={c.get('connection_status', '')}, message={c.get('message_status', '')}",
            "",
        ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", help="Path to a JSON file with one contact dict (or list) to add")
    parser.add_argument("--generate-queue", action="store_true", help="Regenerate reports/networking_queue.md")
    args = parser.parse_args()

    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        records = [data] if isinstance(data, dict) else data
        for raw in records:
            rec = add_contact(raw)
            print(f"Added: {rec['person']} ({rec['role']} @ {rec['company']}) -> priority {rec['priority']}")

    if args.generate_queue or args.from_json:
        out = generate_networking_queue()
        print(f"Networking queue written to {out}")

    if not args.from_json and not args.generate_queue:
        parser.print_help()


if __name__ == "__main__":
    main()
