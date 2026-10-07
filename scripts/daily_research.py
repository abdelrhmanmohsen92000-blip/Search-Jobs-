#!/usr/bin/env python3
"""Daily research cycle orchestrator (V1.2 — live research engine).

Pipeline:
    LOAD PROFILE -> LOAD SEARCH MATRIX -> GENERATE SEARCH QUERIES ->
    RUN ENABLED SOURCE ADAPTERS -> COLLECT RAW RESULTS -> VALIDATE ->
    NORMALIZE -> DEDUPLICATE -> CLASSIFY -> SCORE -> RANK -> SAVE ->
    GENERATE REPORT -> GENERATE NETWORKING QUEUE

SEARCH ENGINE IMPLEMENTATION vs LIVE SEARCH EXECUTION:
This script runs the full pipeline against real source adapters
(scripts/sources/) — Remote OK and Remotive make genuine HTTP calls with
timeouts and retries; Manual Import reads human/browser-session-collected
batches from data/raw/*.json. If a source is unreachable from this
environment (network policy, outage, etc.) it reports
SOURCE_STATUS = UNAVAILABLE with the real error — the pipeline continues
with whatever other sources succeeded, and the report says plainly which
sources ran live and which did not. Nothing here fabricates opportunities.
"""
import argparse
import collections
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib, dedup as dedup_lib, normalize as norm_lib, paths, scoring, storage  # noqa: E402
from scripts.lib import source_health as source_health_lib  # noqa: E402
from scripts import search_config  # noqa: E402
from scripts.application_intelligence import build_plans_for_qualifying  # noqa: E402
from scripts.company_intelligence import hidden_opportunities  # noqa: E402
from scripts.networking_intelligence import generate_networking_queue, load_networking  # noqa: E402
from scripts.sources import REGISTRY as SOURCE_REGISTRY  # noqa: E402
from scripts.intelligence.application_strategy import combined_portfolio_evidence  # noqa: E402
from scripts.intelligence.ai_provider import tier_for_score  # noqa: E402
from scripts.intelligence import opportunity_priority  # noqa: E402
from scripts.lib import opportunity_modes  # noqa: E402

DEFAULT_SUB_SCORES = {  # neutral defaults when a raw record has no explicit scoring input
    "technical": 5, "experience": 5, "software": 5, "project": 5,
    "location": 5, "eligibility": 5, "career_value": 5, "compensation": 5,
}

JOBS_FIELDNAMES = [
    "id", "date_found", "source", "source_url", "job_title", "company", "country", "city",
    "region", "remote", "employment_type", "required_experience", "skills_required",
    "software_required", "project_types", "visa_sponsorship",
    "salary_min", "salary_max", "salary_currency", "salary_period", "salary_source", "salary_confidence",
    "technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation",
    "score", "priority", "recommendation", "action", "status", "notes",
    # Phase 4.2 — appended at the end so older readers/rows are unaffected;
    # list values are "|"-separated (see scripts.lib.opportunity_modes.serialize_list).
    "matched_modes", "discovered_via_modes", "primary_mode", "mode_priority_score",
    "career_priority_score", "career_priority", "exceptional_opportunity", "exceptional_reasons",
    "sub_scores_explicit", "alternate_source_urls",
]

# Columns that hold evidence/identity: on re-discovery an existing non-empty
# value is never overwritten (only blanks are filled). Everything else is a
# derived value and takes the newest computation.
_EVIDENCE_COLUMNS = (
    "id", "date_found", "source", "source_url", "job_title", "company", "country", "city", "region", "remote",
    "employment_type", "required_experience", "skills_required", "software_required", "project_types",
    "visa_sponsorship", "salary_min", "salary_max", "salary_currency", "salary_period", "salary_source",
    "salary_confidence",
)
_UNION_COLUMNS = ("matched_modes", "discovered_via_modes", "exceptional_reasons", "alternate_source_urls")

SUB_SCORE_KEYS = ("technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation")


def opportunity_to_jobs_row(o):
    """Builds one tracking/jobs.csv row from a normalized, scored opportunity.

    Audit finding (production integration audit): the CSV header has always
    declared the 8 V1.1 sub-score columns, but no writer ever populated them
    — every job's technical/experience/.../compensation columns were empty.
    That forced scripts/career_intelligence.py to read from the ephemeral
    data/processed/*.json snapshots instead of the tracking CSV, which is
    supposed to be the durable, canonical record. This is the fix: every
    writer uses this one function, so tracking/jobs.csv is now
    self-sufficient — re-deriving a full scoring_result from a CSV row
    (see career_intelligence.load_opportunities_from_jobs_csv) no longer
    loses the sub-scores.
    """
    sr = o.get("scoring_result") or {}
    row = {
        "id": o["id"], "date_found": o["date_found"], "source": o["source"],
        "source_url": o.get("source_url") or "", "job_title": o["job_title"], "company": o["company"],
        "country": o.get("country") or "", "city": o.get("city") or "", "region": o.get("region") or "",
        "remote": o.get("remote"), "employment_type": o.get("employment_type") or "",
        "required_experience": o.get("experience_required") or "",
        "skills_required": ";".join(o.get("skills_required", [])),
        "software_required": ";".join(o.get("software_required", [])),
        "project_types": ";".join(o.get("project_types", [])),
        "visa_sponsorship": o.get("visa_sponsorship"),
        "salary_min": o.get("salary_min"), "salary_max": o.get("salary_max"),
        "salary_currency": o.get("salary_currency"), "salary_period": o.get("salary_period"),
        "salary_source": o.get("salary_source"), "salary_confidence": o.get("salary_confidence"),
        "score": o.get("match_score"), "priority": o.get("priority"),
        "recommendation": sr.get("recommendation"),
        "action": sr.get("action"), "status": o.get("status"),
        "notes": o.get("reason") or "",
    }
    for key in SUB_SCORE_KEYS:
        row[key] = sr.get(key)
    row.update({
        "matched_modes": opportunity_modes.serialize_list(o.get("matched_modes")),
        "discovered_via_modes": opportunity_modes.serialize_list(o.get("discovered_via_modes")),
        "primary_mode": o.get("primary_mode") or opportunity_modes.UNKNOWN,
        "mode_priority_score": o.get("mode_priority_score"),
        "career_priority_score": o.get("career_priority_score"),
        "career_priority": o.get("career_priority"),
        "exceptional_opportunity": bool(o.get("exceptional_opportunity")),
        "exceptional_reasons": opportunity_modes.serialize_list(o.get("exceptional_reasons")),
        "sub_scores_explicit": sr.get("sub_scores_explicit"),
        "alternate_source_urls": opportunity_modes.serialize_list(
            a.get("source_url") for a in (o.get("alternate_sources") or []) if a.get("source_url")),
    })
    return row


def _merge_jobs_row(existing, new, settings):
    """One canonical row per opportunity: evidence columns keep the first
    non-empty value, list columns are unioned, primary_mode and the
    career-priority fields are recomputed from the merged evidence."""
    merged = dict(existing)
    for key, value in new.items():
        if key in _UNION_COLUMNS:
            combined = opportunity_modes.parse_list(existing.get(key))
            for v in opportunity_modes.parse_list(value if isinstance(value, str) else
                                                   opportunity_modes.serialize_list(value)):
                if v not in combined:
                    combined.append(v)
            merged[key] = opportunity_modes.serialize_list(combined)
        elif key in _EVIDENCE_COLUMNS:
            if existing.get(key) in (None, ""):
                merged[key] = value
        elif value not in (None, ""):
            merged[key] = value

    precedence = settings["ranking"]["primary_mode_precedence"]
    modes = opportunity_modes.parse_list(merged.get("matched_modes"))
    merged["matched_modes"] = opportunity_modes.serialize_list(opportunity_modes._ordered(modes, precedence))
    merged["primary_mode"] = opportunity_modes.resolve_primary_mode(modes, precedence)

    score = merged.get("score")
    opp = {
        "matched_modes": modes, "match_score": float(score) if score not in (None, "") else None,
        "exceptional_reasons": opportunity_modes.parse_list(merged.get("exceptional_reasons")),
        "scoring_result": {
            "sub_scores_explicit": str(merged.get("sub_scores_explicit")) == "True",
            **{k: float(merged[k]) for k in ("career_value", "compensation") if merged.get(k) not in (None, "")},
        },
    }
    opportunity_priority.evaluate_opportunity(opp, settings)
    for key in ("mode_priority_score", "career_priority_score", "career_priority", "exceptional_opportunity"):
        merged[key] = opp[key]
    merged["exceptional_reasons"] = opportunity_modes.serialize_list(opp["exceptional_reasons"])
    return merged


def upsert_jobs_rows(rows, csv_path=None, settings=None):
    """Writes rows to tracking/jobs.csv without creating duplicates: a row
    whose id is already present is merged into the existing row instead of
    appended. Returns (inserted, updated)."""
    csv_path = csv_path or paths.JOBS_CSV
    settings = settings or opportunity_priority.load_settings()
    existing = storage.read_csv(csv_path)
    index = {r.get("id"): i for i, r in enumerate(existing) if r.get("id")}
    inserted = updated = 0
    for row in rows:
        i = index.get(row.get("id"))
        if i is None:  # same job rediscovered at a different URL: existing exact/fuzzy identity rules
            i = next((j for j, r in enumerate(existing) if dedup_lib.fuzzy_match(row, r)), None)
            if i is not None and row.get("source_url") and row.get("source_url") != existing[i].get("source_url"):
                row = {**row, "alternate_source_urls": opportunity_modes.serialize_list(
                    opportunity_modes.parse_list(row.get("alternate_source_urls")) + [row["source_url"]])}
        if i is not None:
            existing[i] = _merge_jobs_row(existing[i], row, settings)
            updated += 1
        else:
            index[row.get("id")] = len(existing)
            existing.append(row)
            inserted += 1
    storage.write_csv(csv_path, JOBS_FIELDNAMES, existing)
    return inserted, updated


def run_source_adapters(enabled_sources=None, limit_per_source=None):
    """RUN ENABLED SOURCE ADAPTERS -> COLLECT RAW RESULTS.

    enabled_sources: optional list of source names to restrict to (--source).
    Returns (raw_records, source_health) where source_health is a list of
    SourceRunResult.to_dict() — recorded for every attempted source,
    success or failure, never silently dropped (PHASE 17 / SOURCE HEALTH).
    """
    if limit_per_source is None:
        limit_per_source = cfg_lib.search_limits()["max_results_per_query"]

    raw_records = []
    source_health = []

    for name, adapter in SOURCE_REGISTRY.items():
        if enabled_sources and name not in enabled_sources:
            continue
        try:
            result = adapter.fetch(limit=limit_per_source)
        except Exception as e:  # noqa: BLE001 - one source's bug must never kill the cycle
            result_dict = {
                "source": name, "status": "ERROR", "error": f"{type(e).__name__}: {e}",
                "opportunities": [], "raw_count": 0, "notes": None,
                "attempted_at": _dt.datetime.now().isoformat(timespec="seconds"),
            }
            source_health.append(result_dict)
            continue
        source_health.append(result.to_dict())
        raw_records.extend(result.opportunities)

    # Sources we know about but don't run automatically every cycle
    # (BROWSER_REQUIRED boards, and PUBLIC_WEB boards needing a per-query
    # target) are still reported so SOURCE HEALTH never hides them.
    for src in search_config.all_sources_with_status():
        name = src.get("name")
        if any(h["source"] == name for h in source_health):
            continue
        if src.get("enabled") is False:
            status = "DISABLED"
        elif src.get("access_method") == "BROWSER_REQUIRED":
            status = "BROWSER_REQUIRED"
        elif src.get("access_method") == "MANUAL":
            status = "MANUAL"
        else:
            status = "NOT_RUN_THIS_CYCLE"
        source_health.append({
            "source": name, "status": status, "error": None, "opportunities": [], "raw_count": 0,
            "notes": f"access_method={src.get('access_method', 'UNKNOWN')}",
            "attempted_at": _dt.datetime.now().isoformat(timespec="seconds"),
        })

    return raw_records, source_health


def normalize_and_score(raw_records, profile=None, discovered_via_mode=None, settings=None):
    """VALIDATE -> NORMALIZE -> CLASSIFY MODES -> DEDUPLICATE (+ merge modes
    and sources into the canonical record) -> SCORE -> PORTFOLIO EVIDENCE ->
    CAREER PRIORITY / EXCEPTIONAL.

    Returns (scored, rejected, duplicates):
        scored    - normalized, deduplicated, scored opportunities
        rejected  - records that failed hard validation (no company or no
                    job_title) with a `rejection_reason`; never silently
                    dropped, just excluded from scoring/ranking
        duplicates - records dropped by deduplication (their sources and
                    modes are folded into the surviving canonical record)
    """
    settings = settings or opportunity_priority.load_settings()
    precedence = settings["ranking"]["primary_mode_precedence"]
    normalized = []
    rejected = []

    for raw in raw_records:
        opp = norm_lib.normalize_opportunity(raw)
        sub_scores = opp.pop("_sub_scores", None)
        errors = norm_lib.validate_opportunity(opp)

        if not opp.get("company") or not opp.get("job_title"):
            rejected.append({**opp, "rejection_reason": "; ".join(errors) or "missing company or job_title"})
            continue

        if errors:
            opp.setdefault("risk_flags", []).append(f"VALIDATION_ERROR: {'; '.join(errors)}")
        if sub_scores:
            opp["_sub_scores"] = sub_scores
        opportunity_modes.apply_mode_classification(opp, discovered_via_mode, precedence)
        normalized.append(opp)

    unique, duplicates = dedup_lib.deduplicate(normalized)
    dedup_lib.attach_duplicates(
        unique, duplicates, on_merge=lambda c, d: opportunity_modes.merge_mode_data(c, d, precedence))

    scored = []
    for opp in unique:
        explicit_sub_scores = opp.get("_sub_scores") is not None
        sub_scores = opp.pop("_sub_scores", None) or DEFAULT_SUB_SCORES
        result = scoring.score_opportunity_record(opp, sub_scores, profile=profile)
        result["sub_scores_explicit"] = explicit_sub_scores
        opp["match_score"] = result["score"]
        opp["priority"] = result["priority"]
        opp["reason"] = "; ".join(result["strengths"][:2]) or "Scored with neutral default sub-scores (no explicit assessment provided)."
        opp["scoring_result"] = result
        opp["status"] = opp.get("status") or "scored"

        # Portfolio evidence (Phase 4): rule-based, zero AI cost, so every
        # normalized opportunity gets it — never gated behind the AI-tier
        # threshold used for the expensive LLM analysis below. Evidence tiers
        # (DIRECT_PROJECT_EVIDENCE > PROFILE_CAPABILITY > REGIONAL_EXPERIENCE)
        # come straight from scripts.intelligence.application_strategy and are
        # never recomputed or weakened here.
        evidence = combined_portfolio_evidence(opp, profile=profile)
        if evidence == "PORTFOLIO_DATA_INSUFFICIENT":
            opp["portfolio_evidence_summary"] = "PORTFOLIO_DATA_INSUFFICIENT"
        else:
            opp["portfolio_evidence_summary"] = {
                "direct_project_matches": [e for e in evidence if e.get("evidence_tier") == "DIRECT_PROJECT_EVIDENCE"],
                "profile_capability_matches": [e for e in evidence if e.get("evidence_tier") == "PROFILE_CAPABILITY"],
                "regional_matches": [e for e in evidence if e.get("evidence_tier") == "REGIONAL_EXPERIENCE"],
            }
        # Career-goal priority and exceptional status (Phase 4.2) — separate
        # fields next to match_score, which is left untouched. Runs after
        # portfolio evidence so it can cite direct project evidence, but never
        # feeds back into that evidence.
        opportunity_priority.evaluate_opportunity(opp, settings)
        scored.append(opp)

    scored.sort(key=lambda o: o.get("match_score") or 0, reverse=True)  # RANK
    return scored, rejected, duplicates


def build_cycle_stats(raw_records, scored, rejected, duplicates, source_health):
    attempted = [h["source"] for h in source_health]
    successful = [h["source"] for h in source_health if h["status"] == "SUCCESS"]
    failed = [h["source"] for h in source_health if h["status"] in ("UNAVAILABLE", "ERROR")]
    tier_breakdown = collections.Counter(tier_for_score(o.get("match_score")) for o in scored)
    return {
        "ai_tier_breakdown": {f"tier_{t}": tier_breakdown.get(t, 0) for t in (1, 2, 3, 4)},
        "execution_timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "sources_attempted": attempted,
        "sources_successful": successful,
        "sources_failed": failed,
        "number_collected": len(raw_records),
        "number_valid": len(scored) + len(duplicates),
        "number_rejected": len(rejected),
        "number_duplicates": len(duplicates),
        "number_new": len(scored),
        "number_high_priority": sum(1 for o in scored if o.get("priority") in ("STRONG", "EXCEPTIONAL")),
        "number_exceptional": sum(1 for o in scored if o.get("priority") == "EXCEPTIONAL"),
        "number_hidden_opportunities": len(hidden_opportunities()),
    }


def market_intelligence(scored):
    countries = collections.Counter(o.get("country") for o in scored if o.get("country"))
    titles = collections.Counter(o.get("job_title") for o in scored if o.get("job_title"))
    companies = collections.Counter(o.get("company") for o in scored if o.get("company"))
    skill_gaps = collections.Counter()
    for o in scored:
        for s in o.get("scoring_result", {}).get("missing_skills", []):
            skill_gaps[s] += 1
    return {
        "best_countries": countries.most_common(5),
        "best_titles": titles.most_common(5),
        "repeat_companies": [(c, n) for c, n in companies.most_common(5) if n > 1],
        "skill_gaps": skill_gaps.most_common(5),
    }


def _opportunity_block(opp, n, show_exceptional=False):
    sr = opp.get("scoring_result", {})
    modes = opp.get("matched_modes") or []
    lines = [
        f"{n}. **{opp.get('job_title')} — {opp.get('company')}**",
        f"   - Match: {opp.get('match_score')}   Current Priority: {opp.get('career_priority') or 'n/a'}"
        f" (career priority score {opp.get('career_priority_score')})",
        f"   - {'Modes' if len(modes) > 1 else 'Mode'}: {opportunity_priority.mode_label(opp)}"
        f"   Primary mode: {opp.get('primary_mode') or 'UNKNOWN'}",
        f"   - Country: {opp.get('country') or 'n/a'}   Action: {sr.get('action')}",
    ]
    if show_exceptional:
        lines.append(f"   - Exceptional: YES — {'; '.join(opp.get('exceptional_explanations') or opp.get('exceptional_reasons') or [])}")
        if opp.get("outside_current_goal"):
            lines.append(f"   - Note: Outside current primary mode ({opp.get('current_career_goal')}), "
                         f"surfaced because it meets the exceptional threshold.")
    elif opp.get("exceptional_opportunity"):
        lines.append("   - Exceptional: YES (see EXCEPTIONAL OPPORTUNITIES)")
    lines.append(f"   - Application URL: {opp.get('source_url') or 'n/a'}")
    return lines


def opportunity_intelligence_lines(scored, settings=None, limit=10):
    """Report sections for Phase 4.2: current goal, top opportunities by
    career priority, exceptional opportunities (including outside the goal),
    and best-match vs best-current-priority."""
    settings = settings or opportunity_priority.load_settings()
    ranked = opportunity_priority.rank_opportunities(scored, settings)
    lines = [f"**Current Career Goal:** {ranked['current_goal'] or 'UNKNOWN'}", "",
             "## TOP CURRENT OPPORTUNITIES", "",
             "_Ordered by career priority: the unchanged match score, weighted by how relevant each job's "
             "evidence-based mode is to the current goal._", ""]
    if not scored:
        lines.append("_None this cycle. See SOURCE HEALTH below for why — most likely all live sources were "
                     "UNAVAILABLE (network policy) and no manual batch was supplied in `data/raw/`._")
    for n, opp in enumerate(ranked["top_current"][:limit], 1):
        lines += _opportunity_block(opp, n) + [""]

    lines += ["## EXCEPTIONAL OPPORTUNITIES", ""]
    if not ranked["exceptional"]:
        lines.append("_None meet the exceptional threshold this cycle (config/career_state.yaml `exceptional`)._")
    for n, opp in enumerate(ranked["exceptional"][:limit], 1):
        lines += _opportunity_block(opp, n, show_exceptional=True) + [""]

    best_match, best_current = ranked["best_match"], ranked["best_current"]
    lines += ["", "## BEST MATCH vs BEST FOR CURRENT GOAL", ""]
    if best_match:
        lines.append(f"- **Best match:** {best_match.get('job_title')} — {best_match.get('company')} "
                     f"(match {best_match.get('match_score')}, {opportunity_priority.mode_label(best_match)})")
        lines.append(f"- **Best for current goal:** {best_current.get('job_title')} — {best_current.get('company')} "
                     f"(match {best_current.get('match_score')}, career priority {best_current.get('career_priority_score')}, "
                     f"{opportunity_priority.mode_label(best_current)})")
    else:
        lines.append("_No opportunities this cycle._")
    lines.append("")
    return lines


def generate_daily_report(scored, rejected, duplicates, stats, query_summary, source_health,
                           application_plans, out_path=None):
    out_path = out_path or (paths.REPORTS_DIR / "daily_report.md")
    today = _dt.date.today().isoformat()

    exceptional = [o for o in scored if o.get("priority") == "EXCEPTIONAL"]
    high_priority = [o for o in scored if o.get("priority") in ("STRONG", "EXCEPTIONAL")]
    freelance = [o for o in scored if (o.get("employment_type") or "").lower() in ("freelance", "contract", "project-based")]

    lines = ["# Career Hunter Daily Intelligence", f"**Date:** {today}", ""]

    lines += ["## Executive Summary", ""]
    live_sources = ", ".join(stats["sources_successful"]) or "none"
    failed_sources = ", ".join(stats["sources_failed"]) or "none"
    lines.append(f"- Sources attempted: {len(stats['sources_attempted'])} | live: {live_sources} | failed/unavailable: {failed_sources}")
    lines.append(f"- New Opportunities: {stats['number_new']}  (Exceptional: {stats['number_exceptional']}, "
                 f"High Priority: {stats['number_high_priority']})")
    lines.append(f"- Freelance: {len(freelance)}")
    lines.append(f"- Hidden Opportunities (all-time): {stats['number_hidden_opportunities']}")
    lines.append(f"- Companies Discovered (all-time): {len(storage.read_csv(paths.COMPANIES_CSV))}")
    lines.append(f"- Networking Targets (all-time): {len(load_networking())}")
    lines.append(f"- Collected: {stats['number_collected']}  Valid: {stats['number_valid']}  "
                 f"Rejected: {stats['number_rejected']}  Duplicates: {stats['number_duplicates']}")
    lines.append("")
    lines.append(f"Query plan this cycle: {query_summary['total_queries']} queries across "
                 f"{query_summary['distinct_titles']} titles, {query_summary['distinct_regions']} region(s), "
                 f"{query_summary['distinct_sources']} sources.")
    lines.append("")

    lines += opportunity_intelligence_lines(scored)

    lines += ["## HIDDEN OPPORTUNITIES", "", "Companies worth approaching even without a public vacancy:", ""]
    hidden = hidden_opportunities()
    if not hidden:
        lines.append("_None logged yet — add companies via `python career_hunter.py companies --from-json <file>`._")
    for c in hidden:
        lines += [
            f"- **{c.get('company_name')}** ({c.get('country', '?')})",
            f"  - Hiring signal: {c.get('hiring_activity') or 'none recorded'}",
            f"  - Relevant department: {c.get('relevant_titles') or 'BIM/Architecture (inferred)'}",
            f"  - Suggested networking target: see tracking/networking.csv for contacts at this company",
            f"  - Recommended action: research decision-makers, then NETWORK_FIRST",
        ]
    lines.append("")

    lines += ["## FREELANCE", ""]
    if not freelance:
        lines.append("_None this cycle._")
    for f in freelance[:10]:
        sr = f.get("scoring_result", {})
        lines.append(f"- **{f.get('job_title')}** via {f.get('source')} — score {f.get('match_score')} "
                      f"({sr.get('action')}) — {f.get('source_url') or 'n/a'}")
    lines.append("")

    lines += ["## NETWORKING", "", "Top people to contact (full drafts in reports/networking_queue.md):", ""]
    contacts = sorted(load_networking(), key=lambda c: float(c.get("network_value_score") or 0), reverse=True)
    if not contacts:
        lines.append("_None logged yet — add contacts via `python career_hunter.py networking --from-json <file>`._")
    for c in contacts[:10]:
        lines.append(f"- **{c.get('person')}** — {c.get('role')} @ {c.get('company')} "
                      f"(priority {c.get('priority')}, score {c.get('network_value_score')})")
    lines.append("")

    lines += ["## FOLLOW UPS", "", "Due today / open applications requiring action:", ""]
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    pending = [a for a in applications if a.get("status") not in ("REJECTED", "CLOSED", "ACCEPTED", "")]
    if not pending:
        lines.append("_No open applications logged in tracking/applications.csv._")
    for a in pending:
        lines.append(f"- {a.get('job_title')} @ {a.get('company')} — status: {a.get('status')} "
                      f"(follow-up: {a.get('follow_up_date') or 'n/a'})")
    lines.append("")

    mi = market_intelligence(scored)
    lines += ["## MARKET INTELLIGENCE", ""]
    lines.append("**Countries producing the best opportunities:** " +
                 (", ".join(f"{c} ({n})" for c, n in mi["best_countries"]) or "n/a"))
    lines.append("**Job titles producing the best matches:** " +
                 (", ".join(f"{t} ({n})" for t, n in mi["best_titles"]) or "n/a"))
    lines.append("**Companies appearing repeatedly:** " +
                 (", ".join(f"{c} ({n})" for c, n in mi["repeat_companies"]) or "none yet"))
    lines.append("**Skill gaps (requested but not yet matched):** " +
                 (", ".join(f"{s} ({n})" for s, n in mi["skill_gaps"]) or "none flagged"))
    lines.append("**Emerging demand:** " + (", ".join(t for t, _ in mi["best_titles"][:3]) or "insufficient data yet"))
    lines.append("")

    lines += ["## SOURCE HEALTH", "", "| Source | Status | Results | Errors |", "|---|---|---|---|"]
    for h in source_health:
        lines.append(f"| {h['source']} | {h['status']} | {len(h.get('opportunities', [])) or h.get('raw_count', 0)} "
                      f"| {h.get('error') or '-'} |")
    lines.append("")

    tb = stats.get("ai_tier_breakdown", {})
    lines += ["## AI ANALYSIS", "",
              f"Tier 1 (rule-based only): {tb.get('tier_1', 0)}  "
              f"Tier 2 (job analysis): {tb.get('tier_2', 0)}  "
              f"Tier 3 (deep analysis): {tb.get('tier_3', 0)}  "
              f"Tier 4 (full application strategy): {tb.get('tier_4', 0)}",
              "", "Tiers 2-4 are the only ones that call an AI provider — never sent automatically if "
              "ANTHROPIC_API_KEY is unset, in which case the rule-based provider (free, zero-network) "
              "is used instead.", ""]

    with_evidence = [o for o in scored if o.get("portfolio_evidence_summary") not in (None, "PORTFOLIO_DATA_INSUFFICIENT")]
    lines += ["## PORTFOLIO EVIDENCE", "",
              f"{len(with_evidence)} of {len(scored)} opportunities this cycle have at least one portfolio-evidence "
              "match (direct project, profile capability, or regional experience).", ""]
    for o in with_evidence[:10]:
        summary = o["portfolio_evidence_summary"]
        parts = []
        if summary["direct_project_matches"]:
            parts.append("DIRECT: " + ", ".join(m["project"] for m in summary["direct_project_matches"]))
        if summary["profile_capability_matches"]:
            parts.append("CAPABILITY: " + ", ".join(m["capability"] for m in summary["profile_capability_matches"]))
        if summary["regional_matches"]:
            parts.append("REGIONAL: " + ", ".join(m["region"] for m in summary["regional_matches"]))
        lines.append(f"- **{o.get('job_title')} @ {o.get('company')}** — " + " | ".join(parts))
    lines.append("")

    if rejected:
        lines += ["## Rejected Records", "", f"{len(rejected)} record(s) rejected this cycle (reason logged, not discarded silently):", ""]
        for r in rejected[:10]:
            lines.append(f"- {r.get('job_title') or '(no title)'} @ {r.get('company') or '(no company)'} — {r.get('rejection_reason')}")
        lines.append("")

    if duplicates:
        lines += ["## Deduplication", "", f"{len(duplicates)} duplicate record(s) dropped this cycle.", ""]

    if application_plans:
        lines += ["## Application Preparation (score >= 80)", ""]
        for plan in application_plans:
            lines.append(f"- **{plan['job_title']} @ {plan['company']}** (score {plan['score']}) — "
                          f"see data/processed/ snapshot for full CV/cover-letter/interview guidance.")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run(region=None, remote=False, freelance=False, source_filter=None, limit=None, dry_run=False,
        employment_types=None, mode=None):
    """mode/employment_types (Phase 4.1 Career Search Modes Engine): an
    optional label + employment-type override from scripts.lib.career_state,
    e.g. running the CONTRACT mode passes employment_types=["Contract"].
    Neither changes default behavior when omitted (existing callers
    unaffected) — mode is purely a label carried into stats for reporting.
    """
    profile = cfg_lib.load_profile_skills()  # LOAD PROFILE
    cfg_lib.load_search_matrix()  # LOAD SEARCH MATRIX

    query_plan = search_config.build_query_plan(  # GENERATE SEARCH QUERIES
        region=region, remote_only=remote, freelance_only=freelance, source_filter=source_filter, limit=limit,
        employment_types=employment_types,
    )
    query_summary = search_config.summarize_plan(query_plan)

    if dry_run:
        return {"dry_run": True, "query_summary": query_summary, "query_plan_sample": query_plan[:10], "mode": mode}

    enabled = [source_filter] if source_filter else None
    raw_records, source_health = run_source_adapters(enabled_sources=enabled, limit_per_source=limit)  # RUN SOURCES / COLLECT
    persistent_source_health = source_health_lib.update_source_health(source_health)  # cross-run health history

    settings = opportunity_priority.load_settings()
    scored, rejected, duplicates = normalize_and_score(raw_records, profile=profile, discovered_via_mode=mode,
                                                       settings=settings)  # VALIDATE/NORMALIZE/MODES/DEDUP/SCORE/RANK
    stats = build_cycle_stats(raw_records, scored, rejected, duplicates, source_health)
    stats["career_mode"] = mode

    storage.save_run_snapshot("processed", "daily_opportunities", scored)  # SAVE

    if scored:
        inserted, updated = upsert_jobs_rows([opportunity_to_jobs_row(o) for o in scored], settings=settings)
        stats["jobs_inserted"], stats["jobs_updated"] = inserted, updated

    application_plans = build_plans_for_qualifying(scored)  # application intelligence, score >= 80
    if application_plans:
        storage.save_run_snapshot("processed", "application_plans", application_plans)

    report_path = generate_daily_report(scored, rejected, duplicates, stats, query_summary, source_health,
                                         application_plans)  # GENERATE REPORT
    generate_networking_queue()  # GENERATE NETWORKING QUEUE

    return {"dry_run": False, "report_path": report_path, "scored": scored, "stats": stats,
            "source_health": source_health, "persistent_source_health": persistent_source_health,
            "query_summary": query_summary, "mode": mode}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=None)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--freelance", action="store_true")
    parser.add_argument("--source", default=None, help="Restrict to a single source by name")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = run(region=args.region, remote=args.remote, freelance=args.freelance,
                 source_filter=args.source, limit=args.limit, dry_run=args.dry_run)

    if result["dry_run"]:
        import json as _json
        print(_json.dumps(result["query_summary"], indent=2))
        print(f"(dry run — {result['query_summary']['total_queries']} queries would be generated; "
              f"no trackers or reports were modified)")
    else:
        print(f"Report written to {result['report_path']} ({len(result['scored'])} opportunities scored this cycle)")


if __name__ == "__main__":
    main()
