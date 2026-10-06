"""Decision engine (V1.4).

Produces one final, explained decision per opportunity from the V1.1
match_score/action and the V1.4 job_analyzer output — never a second,
conflicting scoring model. Also computes ACTION_PRIORITY, a single sortable
number for the daily action queue, and records decision history (why a
decision was made) for future learning.
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.lib import paths, storage  # noqa: E402

DECISIONS = ("APPLY_NOW", "APPLY", "NETWORK_FIRST", "RESEARCH_COMPANY", "CONSIDER", "LOW_PRIORITY", "SKIP")

DECISIONS_FIELDNAMES = [
    "opportunity_id", "company", "job_title", "decision", "reason", "match_score",
    "ai_opportunity_score", "action_priority", "timestamp", "evidence", "next_action",
]


def decide(opportunity, job_analysis, company_analysis=None):
    """opportunity: normalized, scored opportunity (has scoring_result).
    job_analysis: output of job_analyzer.analyze_job().
    company_analysis: optional output of company_analyzer.analyze_company().

    Returns {decision, why (list[str]), risks (list[str]), next_action}.
    """
    match_score = opportunity.get("match_score") or 0
    ai_score = job_analysis["ai_opportunity_score"]
    risk_score = job_analysis["risk_score"]
    hidden_opportunity = bool(company_analysis and company_analysis.get("potential_hidden_opportunity"))

    why = []
    if job_analysis["fit_score"] >= 80:
        why.append(f"Strong technical/role fit ({job_analysis['fit_score']}%).")
    matched = [r["requirement"] for r in job_analysis["skill_gap"] if r["status"] == "MATCH"]
    if matched:
        why.append(f"Matches required skills/software: {', '.join(matched)}.")
    if job_analysis["quality_score"] >= 70:
        why.append(f"High opportunity quality (company/career/compensation signal: {job_analysis['quality_score']}).")

    risks = list(job_analysis["risk_factors"])

    if hidden_opportunity and match_score < 70:
        decision = "NETWORK_FIRST"
        next_action = "Identify a BIM/hiring decision-maker at this company and reach out before any vacancy is posted."
        if not why:
            why.append("Company shows a hiring/BIM signal without a confirmed public vacancy.")
    elif match_score >= 90 and risk_score < 30:
        decision = "APPLY_NOW"
        next_action = "Submit a tailored CV and portfolio immediately; identify and contact the BIM/hiring manager."
    elif match_score >= 70:
        decision = "APPLY"
        next_action = "Submit a tailored application within the next application cycle."
    elif match_score >= 50 and risk_score >= 40:
        decision = "RESEARCH_COMPANY"
        next_action = "Research the company further (BIM activity, hiring signals) before deciding to apply or network."
        if not why:
            why.append("Moderate match with unresolved risk factors — more information needed before acting.")
    elif match_score >= 50:
        decision = "CONSIDER"
        next_action = "Keep in the pipeline; revisit if higher-priority opportunities are exhausted."
        if not why:
            why.append("Moderate match with no major risk flags.")
    elif match_score >= 25:
        decision = "LOW_PRIORITY"
        next_action = "No action needed now; log for market awareness."
    else:
        decision = "SKIP"
        next_action = "Do not pursue — match is too weak to justify effort."

    if not why:
        why.append(f"Match score {match_score} with {risk_score} risk points — see risks for detail.")

    return {"decision": decision, "why": why, "risks": risks or ["No major risks flagged."], "next_action": next_action}


def compute_action_priority(opportunity, job_analysis, decision_result):
    """One sortable 0-100 number combining match, AI opportunity score,
    confidence, career value, and company quality — purely for ranking the
    daily action queue. Does NOT replace match_score or ai_opportunity_score;
    those remain available individually on every report.
    """
    match_score = opportunity.get("match_score") or 0
    ai_score = job_analysis["ai_opportunity_score"]
    confidence = opportunity.get("confidence_score")
    confidence = float(confidence) if confidence is not None else 70.0  # neutral default for non-web-sourced jobs
    career_value = float((opportunity.get("scoring_result") or {}).get("career_value") or 5) * 10

    urgency_bonus = 10 if decision_result["decision"] == "APPLY_NOW" else (5 if decision_result["decision"] == "NETWORK_FIRST" else 0)

    priority = (match_score * 0.35 + ai_score * 0.30 + confidence * 0.15 + career_value * 0.20) + urgency_bonus
    return round(min(priority, 100), 1)


def record_decision(opportunity, job_analysis, decision_result, action_priority, csv_path=None):
    """Appends one row to tracking/decisions.csv — decision history for
    future learning (V1.4 Phase 21). Never overwrites prior rows.
    """
    csv_path = csv_path or paths.DECISIONS_CSV
    row = {
        "opportunity_id": opportunity.get("id", ""),
        "company": opportunity.get("company", ""),
        "job_title": opportunity.get("job_title", ""),
        "decision": decision_result["decision"],
        "reason": "; ".join(decision_result["why"]),
        "match_score": opportunity.get("match_score"),
        "ai_opportunity_score": job_analysis["ai_opportunity_score"],
        "action_priority": action_priority,
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "evidence": "; ".join(decision_result["risks"]),
        "next_action": decision_result["next_action"],
    }
    storage.append_csv_rows(csv_path, DECISIONS_FIELDNAMES, [row])
    return row
