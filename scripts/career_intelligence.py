#!/usr/bin/env python3
"""Career Intelligence pipeline orchestrator (V1.4).

    LOAD -> ANALYZE -> SCORE -> DECIDE -> NETWORK -> APPLICATION STRATEGY -> REPORT -> LEARN

Operates on already-normalized-and-scored opportunities (the full
scoring_result, including the 8 V1.1 sub-scores, is only available in the
JSON snapshots scripts/daily_research.py and scripts/web_research.py already
save to data/processed/ — tracking/jobs.csv itself does not persist the
sub-scores). LOAD therefore reads the latest such snapshots rather than
tracking/jobs.csv directly; this adds no new coupling to those pipelines and
changes nothing about how they run.

This module never sends anything, never applies anything, and never
automates LinkedIn/email/browser actions — it only analyzes, decides, drafts,
and reports. Human approval remains mandatory for every outward action.
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import paths, storage  # noqa: E402
from scripts.intelligence import ai_provider, company_analyzer, cv_strategy, decision_engine, job_analyzer  # noqa: E402
from scripts.intelligence.application_strategy import build_strategy  # noqa: E402
from scripts.company_intelligence import load_companies  # noqa: E402

SNAPSHOT_PATTERNS = ("daily_opportunities.*.json", "web_import_opportunities.*.json")


def load_latest_scored_opportunities():
    """LOAD: merges the most recent snapshot of each known kind from
    data/processed/, deduplicated by opportunity id (latest file wins per id).
    Returns [] (never fake data) if no snapshot exists yet.
    """
    if not paths.DATA_PROCESSED.exists():
        return []

    by_id = {}
    for pattern in SNAPSHOT_PATTERNS:
        files = sorted(paths.DATA_PROCESSED.glob(pattern))
        for f in files:  # oldest to newest, so the newest overwrites
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for opp in data:
                if opp.get("id"):
                    by_id[opp["id"]] = opp
    return list(by_id.values())


def _company_lookup():
    companies = load_companies()
    return {c["company_name"].strip().lower(): c for c in companies if c.get("company_name")}


def analyze_opportunities(opportunities=None, score_min=0, deep=False):
    """ANALYZE -> (SCORE already done) -> DECIDE -> NETWORK (company lookup only).

    Applies AI-cost-control tiering (scripts.intelligence.ai_provider): below
    tier_2_min, only the decision engine's cheap rule runs; tier 2+ runs the
    full job_analyzer; `deep=True` forces tier-3-equivalent depth regardless
    of score (still never fabricates — just computes the same honest metrics
    for lower-scoring records too, useful for manual review).

    Returns a list of enriched dicts: the original opportunity plus
    `job_analysis`, `company_analysis`, `decision`, `action_priority`, and
    (for score >= application_intelligence.THRESHOLD) `application_strategy`.
    """
    from scripts.application_intelligence import THRESHOLD as APPLICATION_THRESHOLD

    opportunities = opportunities if opportunities is not None else load_latest_scored_opportunities()
    company_lookup = _company_lookup()
    tiers = ai_provider.get_tiers()
    results = []

    for opp in opportunities:
        score = opp.get("match_score") or 0
        if score < score_min:
            continue

        tier = 4 if deep else ai_provider.tier_for_score(score, tiers)
        if tier < 2 and not deep:
            continue  # TIER 1: rule-based scoring only, no AI analysis — cost control

        company_record = company_lookup.get((opp.get("company") or "").strip().lower())
        company_analysis = company_analyzer.analyze_company(company_record) if company_record else None

        analysis = job_analyzer.analyze_job(opp, company_analysis)
        decision_result = decision_engine.decide(opp, analysis, company_analysis)
        action_priority = decision_engine.compute_action_priority(opp, analysis, decision_result)

        enriched = {
            **opp,
            "job_analysis": analysis,
            "company_analysis": company_analysis,
            "decision": decision_result,
            "action_priority": action_priority,
        }

        if score >= APPLICATION_THRESHOLD:
            cv_plan = cv_strategy.generate_cv_change_plan(opp, analysis)
            enriched["application_strategy"] = build_strategy(opp, analysis, cv_plan, decision_result)

        results.append(enriched)

    results.sort(key=lambda o: o["action_priority"], reverse=True)
    return results


def record_decisions(enriched_opportunities):
    for opp in enriched_opportunities:
        decision_engine.record_decision(opp, opp["job_analysis"], opp["decision"], opp["action_priority"])


def generate_alerts(enriched_opportunities, company_lookup=None):
    """Machine-readable alert conditions (V1.4 Phase 20). Written to
    data/alerts/<timestamp>.json, tracking/alerts.csv, and reports/alerts.md.
    Never sent anywhere automatically.
    """
    alerts = []
    now = _dt.datetime.now().isoformat(timespec="seconds")

    for opp in enriched_opportunities:
        score = opp.get("match_score") or 0
        if opp.get("priority") == "EXCEPTIONAL":
            alerts.append({"alert_type": "NEW_EXCEPTIONAL_OPPORTUNITY", "severity": "HIGH", "opportunity_id": opp.get("id"),
                            "company": opp.get("company"), "job_title": opp.get("job_title"),
                            "details": f"Match score {score}."})
        elif score >= 85:
            alerts.append({"alert_type": "HIGH_MATCH_JOB", "severity": "MEDIUM", "opportunity_id": opp.get("id"),
                            "company": opp.get("company"), "job_title": opp.get("job_title"),
                            "details": f"Match score {score}."})
        if opp.get("company_analysis") and opp["company_analysis"].get("company_priority") in ("A+", "A"):
            alerts.append({"alert_type": "HIGH_VALUE_COMPANY", "severity": "MEDIUM", "opportunity_id": opp.get("id"),
                            "company": opp.get("company"), "job_title": opp.get("job_title"),
                            "details": f"Company priority {opp['company_analysis']['company_priority']}."})
        if opp.get("company_analysis") and opp["company_analysis"].get("potential_hidden_opportunity"):
            alerts.append({"alert_type": "NEW_HIDDEN_OPPORTUNITY", "severity": "MEDIUM", "opportunity_id": opp.get("id"),
                            "company": opp.get("company"), "job_title": opp.get("job_title"),
                            "details": "Hidden opportunity — no confirmed vacancy, strong signal."})

    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    for a in applications:
        status = (a.get("status") or "").strip().upper()
        if status == "INTERVIEW":
            alerts.append({"alert_type": "INTERVIEW", "severity": "HIGH", "opportunity_id": a.get("opportunity_id"),
                            "company": a.get("company"), "job_title": a.get("job_title"), "details": "Interview stage."})
        elif status == "OFFER":
            alerts.append({"alert_type": "OFFER", "severity": "HIGH", "opportunity_id": a.get("opportunity_id"),
                            "company": a.get("company"), "job_title": a.get("job_title"), "details": "Offer received."})
        follow_up = a.get("follow_up_date")
        if follow_up and follow_up <= _dt.date.today().isoformat() and status not in ("CLOSED", "REJECTED", "ACCEPTED"):
            alerts.append({"alert_type": "FOLLOW_UP_DUE", "severity": "MEDIUM", "opportunity_id": a.get("opportunity_id"),
                            "company": a.get("company"), "job_title": a.get("job_title"),
                            "details": f"Follow-up was due {follow_up}."})

    for alert in alerts:
        alert["timestamp"] = now

    if alerts:
        fieldnames = ["timestamp", "alert_type", "severity", "opportunity_id", "company", "job_title", "details"]
        storage.append_csv_rows(paths.ALERTS_CSV, fieldnames, alerts)
        storage.save_run_snapshot("alerts", "alerts", alerts)

    return alerts


def generate_alerts_report(alerts, out_path=None):
    out_path = out_path or (paths.REPORTS_DIR / "alerts.md")
    lines = [f"# Alerts — {_dt.date.today().isoformat()}", ""]
    if not alerts:
        lines.append("_No alerts this cycle._")
    for a in alerts:
        lines.append(f"- **[{a['severity']}] {a['alert_type']}** — {a.get('job_title', '')} @ {a.get('company', '')}: {a['details']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def generate_career_command_report(enriched_opportunities, out_path=None):
    """CAREER COMMAND REPORT (V1.4 Phase 18) — overwrites reports/daily_report.md
    with the richer, decision-first format. `daily_research.py`'s own report
    writer is untouched and still runs standalone via `career_hunter.py daily`.
    """
    out_path = out_path or (paths.REPORTS_DIR / "daily_report.md")
    today = _dt.date.today().isoformat()

    exceptional = [o for o in enriched_opportunities if o.get("priority") == "EXCEPTIONAL"]
    high_priority = [o for o in enriched_opportunities if o.get("priority") in ("STRONG", "EXCEPTIONAL")]
    apply_now = [o for o in enriched_opportunities if o["decision"]["decision"] == "APPLY_NOW"]
    network_first = [o for o in enriched_opportunities if o["decision"]["decision"] == "NETWORK_FIRST"]
    freelance = [o for o in enriched_opportunities if (o.get("employment_type") or "").lower() in ("freelance", "contract", "project-based")]
    hidden = [o for o in enriched_opportunities if o.get("company_analysis") and o["company_analysis"].get("potential_hidden_opportunity")]

    lines = ["# CAREER COMMAND REPORT", f"**Date:** {today}", ""]

    lines += ["## EXECUTIVE SUMMARY", ""]
    lines.append(f"- New Opportunities: {len(enriched_opportunities)}")
    lines.append(f"- High Priority: {len(high_priority)}  Exceptional: {len(exceptional)}")
    lines.append(f"- Freelance: {len(freelance)}")
    lines.append(f"- Hidden Opportunities: {len(hidden)}")
    lines.append(f"- Networking Targets (all-time): {len(storage.read_csv(paths.NETWORKING_CSV))}")
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    pending = [a for a in applications if (a.get("status") or "").upper() not in ("REJECTED", "CLOSED", "ACCEPTED", "")]
    lines.append(f"- Follow-ups due: {len(pending)}")
    lines.append("")

    lines += ["## TOP 10 ACTIONS", ""]
    if not enriched_opportunities:
        lines.append("_No analyzed opportunities this cycle — run `career_hunter.py daily`/`web-import` first, "
                      "then `career_hunter.py analyze` or `intelligence`._")
    for rank, o in enumerate(enriched_opportunities[:10], 1):
        d = o["decision"]
        lines += [
            f"### {rank}. {d['decision']} — {o.get('job_title')} @ {o.get('company')} (priority {o['action_priority']})",
            f"- **Country:** {o.get('country') or 'n/a'}  **Score:** {o.get('match_score')}",
            f"- **Why:** {'; '.join(d['why'])}",
            f"- **Risk:** {'; '.join(d['risks'])}",
            f"- **Next Action:** {d['next_action']}",
            "",
        ]

    lines += ["## APPLY NOW", ""]
    if not apply_now:
        lines.append("_None this cycle._")
    for o in apply_now:
        lines.append(f"- {o.get('job_title')} @ {o.get('company')} — {o.get('source_url') or 'n/a'}")
    lines.append("")

    lines += ["## NETWORK FIRST", ""]
    if not network_first:
        lines.append("_None this cycle._")
    for o in network_first:
        lines.append(f"- {o.get('company')}: {o['decision']['next_action']}")
    lines.append("")

    from scripts.company_intelligence import hidden_opportunities as all_hidden_companies
    hidden_companies = all_hidden_companies()
    lines += ["## HIDDEN OPPORTUNITIES", ""]
    if not hidden_companies:
        lines.append("_None logged yet — add companies via `python career_hunter.py companies --from-json <file>`._")
    for c in hidden_companies:
        matched_opp = next((o for o in hidden if (o.get("company") or "").strip().lower() == c["company_name"].strip().lower()), None)
        action = matched_opp["company_analysis"]["recommended_networking_action"] if matched_opp else "NETWORK_FIRST — research and identify a decision-maker."
        lines.append(f"- **{c['company_name']}** ({c.get('country', '?')}, fit {c.get('ai_fit_score')}) — {action}")
    lines.append("")

    lines += ["## FREELANCE", ""]
    if not freelance:
        lines.append("_None this cycle._")
    for o in freelance:
        lines.append(f"- {o.get('job_title')} — score {o.get('match_score')} ({o['decision']['decision']})")
    lines.append("")

    lines += ["## FOLLOW UPS", ""]
    if not pending:
        lines.append("_No open applications logged._")
    for a in pending:
        lines.append(f"- {a.get('job_title')} @ {a.get('company')} — status {a.get('status')}")
    lines.append("")

    from scripts.intelligence.skill_gap import missing_skill_frequency
    freq = missing_skill_frequency()
    lines += ["## SKILL INTELLIGENCE", ""]
    lines += [f"- {skill}: requested {count}x" for skill, count in freq.most_common(10)] or ["_No data yet._"]
    lines.append("")

    from scripts.intelligence.career_strategy import market_intelligence
    mi = market_intelligence()
    lines += ["## MARKET INTELLIGENCE", ""]
    lines.append(f"Sample size: {mi['sample_size']} (confidence: {mi['confidence']})")
    lines.append("Countries: " + (", ".join(f"{c} ({n})" for c, n in mi["strongest_demand_countries"][:5]) or "n/a"))
    lines.append("Titles: " + (", ".join(f"{t} ({n})" for t, n in mi["most_common_job_titles"][:5]) or "n/a"))
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run_intelligence_cycle(score_min=0, deep=False):
    """LOAD -> ANALYZE -> SCORE -> DECIDE -> NETWORK -> APPLICATION STRATEGY -> REPORT -> LEARN."""
    enriched = analyze_opportunities(score_min=score_min, deep=deep)
    record_decisions(enriched)
    alerts = generate_alerts(enriched)
    generate_alerts_report(alerts)
    report_path = generate_career_command_report(enriched)

    from scripts.intelligence.learning_engine import full_learning_report, record_learning_snapshot
    learning = full_learning_report()
    record_learning_snapshot(learning)

    return {"enriched": enriched, "alerts": alerts, "report_path": report_path, "learning": learning}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-min", type=float, default=0)
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    result = run_intelligence_cycle(score_min=args.score_min, deep=args.deep)
    print(f"Analyzed {len(result['enriched'])} opportunities. Report: {result['report_path']}. "
          f"Alerts: {len(result['alerts'])}.")


if __name__ == "__main__":
    main()
