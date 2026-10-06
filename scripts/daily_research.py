#!/usr/bin/env python3
"""Daily research cycle orchestrator.

Pipeline:
    LOAD PROFILE -> LOAD SEARCH MATRIX -> GENERATE SEARCH QUERIES ->
    SEARCH SOURCES -> COLLECT OPPORTUNITIES -> NORMALIZE -> DEDUPLICATE ->
    SCORE -> SAVE -> GENERATE REPORT

IMPORTANT — SEARCH ENGINE IMPLEMENTATION vs LIVE SEARCH EXECUTION:
This script implements the full pipeline (query generation, normalization,
dedup, scoring, reporting). It does NOT perform live web requests — this
sandboxed environment has no outbound browsing/API access to job boards or
LinkedIn. "SEARCH SOURCES / COLLECT OPPORTUNITIES" is satisfied by reading
raw opportunity dicts that a human or a web-enabled agent session has placed
in data/raw/*.json (one file per collection batch; each file is a JSON list
of loosely-shaped opportunity dicts). If no such files exist, the report
says so explicitly rather than fabricating results.

See README.md "What requires browser/web access" for exactly what external
access would turn this into a fully live system.
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib, dedup as dedup_lib, normalize as norm_lib, paths, scoring, storage  # noqa: E402
from scripts import search_config  # noqa: E402
from scripts.company_intelligence import hidden_opportunities  # noqa: E402
from scripts.networking_intelligence import load_networking  # noqa: E402

DEFAULT_SUB_SCORES = {  # neutral defaults when a raw record has no explicit scoring input
    "technical": 5, "experience": 5, "software": 5, "project": 5,
    "location": 5, "eligibility": 5, "career_value": 5, "compensation": 5,
}


def collect_raw_opportunities():
    """Reads every JSON file in data/raw/ (each a list of raw opportunity
    dicts) as the "collected" batch for this cycle. Returns (records, files_read).
    """
    records = []
    files_read = []
    if not paths.DATA_RAW.exists():
        return records, files_read
    for f in sorted(paths.DATA_RAW.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        batch = data if isinstance(data, list) else [data]
        records.extend(batch)
        files_read.append(str(f.relative_to(paths.ROOT)))
    return records, files_read


def normalize_and_score(raw_records, profile=None):
    normalized = []
    for raw in raw_records:
        opp = norm_lib.normalize_opportunity(raw)
        sub_scores = opp.pop("_sub_scores", None)
        errors = norm_lib.validate_opportunity(opp)
        if errors:
            opp.setdefault("risk_flags", []).append(f"VALIDATION_ERROR: {'; '.join(errors)}")
        if sub_scores:
            opp["_sub_scores"] = sub_scores
        normalized.append(opp)

    unique, duplicates = dedup_lib.deduplicate(normalized)

    scored = []
    for opp in unique:
        sub_scores = opp.pop("_sub_scores", None) or DEFAULT_SUB_SCORES
        result = scoring.score_opportunity_record(opp, sub_scores, profile=profile)
        opp["match_score"] = result["score"]
        opp["priority"] = result["priority"]
        opp["reason"] = "; ".join(result["strengths"][:2]) or "Scored with neutral default sub-scores (no explicit assessment provided)."
        opp["scoring_result"] = result
        opp["status"] = opp.get("status") or "scored"
        scored.append(opp)

    scored.sort(key=lambda o: o.get("match_score") or 0, reverse=True)
    return scored, duplicates


def generate_daily_report(scored, duplicates, files_read, query_summary, out_path=None):
    out_path = out_path or (paths.REPORTS_DIR / "daily_report.md")
    today = _dt.date.today().isoformat()

    lines = [f"# Daily Research Report — {today}", ""]

    lines += ["## Execution mode", ""]
    if files_read:
        lines.append(f"**LIVE SEARCH EXECUTION:** partial — {len(files_read)} raw batch file(s) processed "
                      f"from `data/raw/`: {', '.join(files_read)}.")
    else:
        lines.append("**LIVE SEARCH EXECUTION: NOT PERFORMED.** No raw opportunity data found in `data/raw/`. "
                      "This environment has no outbound web/browser access to job boards or LinkedIn. "
                      "The query plan below (SEARCH ENGINE IMPLEMENTATION) is ready to execute once opportunity "
                      "data is supplied — see README.md 'What requires browser/web access'.")
    lines.append("")
    lines.append(f"Query plan generated this cycle: {query_summary['total_queries']} queries across "
                 f"{query_summary['distinct_titles']} titles, {query_summary['distinct_regions']} regions, "
                 f"{query_summary['distinct_sources']} sources.")
    lines.append("")

    lines += ["## TOP 10 OPPORTUNITIES", ""]
    if not scored:
        lines.append("_None — no opportunity data available this cycle._")
    for opp in scored[:10]:
        sr = opp.get("scoring_result", {})
        lines += [
            f"### {opp.get('job_title')} — {opp.get('company')}",
            f"- **Country:** {opp.get('country') or 'n/a'}  **Work mode:** {opp.get('employment_type') or 'n/a'}"
            f"{' (remote)' if opp.get('remote') else ''}",
            f"- **Match score:** {opp.get('match_score')} ({opp.get('priority')}, {sr.get('recommendation')})",
            f"- **Why:** {'; '.join(sr.get('strengths', [])) or 'n/a'}",
            f"- **Risks:** {'; '.join(sr.get('risks', [])) or 'none flagged'}",
            f"- **Recommended action:** {sr.get('recommendation')}",
            f"- **Source URL:** {opp.get('source_url') or 'n/a'}",
            "",
        ]

    lines += ["## HIDDEN OPPORTUNITIES", "", "Companies worth approaching even without a public vacancy:", ""]
    hidden = hidden_opportunities()
    if not hidden:
        lines.append("_None logged yet — add companies via `python3 career_hunter.py companies --from-json <file>`._")
    for c in hidden:
        lines.append(f"- **{c.get('company_name')}** ({c.get('country', '?')}) — fit {c.get('ai_fit_score')}: "
                      f"{c.get('bim_activity') or c.get('hiring_activity') or 'relevant signal logged'}")
    lines.append("")

    lines += ["## NETWORKING TARGETS", "", "People worth connecting with (see reports/networking_queue.md for full drafts):", ""]
    contacts = sorted(load_networking(), key=lambda c: float(c.get("network_value_score") or 0), reverse=True)
    if not contacts:
        lines.append("_None logged yet — add contacts via `python3 career_hunter.py networking --from-json <file>`._")
    for c in contacts[:10]:
        lines.append(f"- **{c.get('person')}** — {c.get('role')} @ {c.get('company')} "
                      f"(priority {c.get('priority')}, score {c.get('network_value_score')})")
    lines.append("")

    lines += ["## FOLLOW-UPS", "", "Applications and contacts requiring action:", ""]
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    pending = [a for a in applications if a.get("status") not in ("rejected", "offer", "")]
    if not pending:
        lines.append("_No open applications logged in tracking/applications.csv._")
    for a in pending:
        lines.append(f"- {a.get('job_title')} @ {a.get('company')} — status: {a.get('status')}")
    lines.append("")

    if duplicates:
        lines += [f"## Deduplication", "", f"{len(duplicates)} duplicate record(s) dropped this cycle.", ""]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run(region=None, remote=False, freelance=False):
    profile = cfg_lib.load_profile_skills()  # LOAD PROFILE
    cfg_lib.load_search_matrix()  # LOAD SEARCH MATRIX

    query_plan = search_config.build_query_plan(region=region, remote_only=remote, freelance_only=freelance)  # GENERATE SEARCH QUERIES
    query_summary = search_config.summarize_plan(query_plan)

    raw_records, files_read = collect_raw_opportunities()  # SEARCH SOURCES / COLLECT OPPORTUNITIES
    scored, duplicates = normalize_and_score(raw_records, profile=profile)  # NORMALIZE / DEDUPLICATE / SCORE

    storage.save_run_snapshot("processed", "daily_opportunities", scored)  # SAVE

    if scored:
        jobs_fieldnames = [
            "id", "date_found", "source", "source_url", "job_title", "company", "country", "city",
            "region", "remote", "employment_type", "required_experience", "skills_required",
            "software_required", "project_types", "visa_sponsorship", "technical", "experience",
            "software", "project", "location", "eligibility", "career_value", "compensation",
            "score", "priority", "recommendation", "status", "notes",
        ]
        storage.append_csv_rows(
            paths.JOBS_CSV,
            jobs_fieldnames,
            [
                {
                    "id": o["id"], "date_found": o["date_found"], "source": o["source"],
                    "source_url": o.get("source_url") or "", "job_title": o["job_title"], "company": o["company"],
                    "country": o.get("country") or "", "city": o.get("city") or "", "region": o.get("region") or "",
                    "remote": o.get("remote"), "employment_type": o.get("employment_type") or "",
                    "required_experience": o.get("experience_required") or "",
                    "skills_required": ";".join(o.get("skills_required", [])),
                    "software_required": ";".join(o.get("software_required", [])),
                    "project_types": ";".join(o.get("project_types", [])),
                    "visa_sponsorship": o.get("visa_sponsorship"),
                    "score": o.get("match_score"), "priority": o.get("priority"),
                    "recommendation": o["scoring_result"]["recommendation"], "status": o.get("status"),
                    "notes": o.get("reason") or "",
                }
                for o in scored
            ],
        )

    report_path = generate_daily_report(scored, duplicates, files_read, query_summary)
    return report_path, scored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=None)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--freelance", action="store_true")
    args = parser.parse_args()

    report_path, scored = run(region=args.region, remote=args.remote, freelance=args.freelance)
    print(f"Report written to {report_path} ({len(scored)} opportunities scored this cycle)")


if __name__ == "__main__":
    main()
