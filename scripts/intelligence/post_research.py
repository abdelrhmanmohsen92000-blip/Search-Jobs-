"""Steps that run after any research/import cycle has scored and saved jobs (V1.4/V1.5).

    save analyses -> networking suggestions -> notifications for new high-priority jobs

Shared by scripts/daily_research.py (live/offline research), scripts/web_research.py
(web-import) and the synthetic demo, so every entry point produces the same
downstream records. Nothing here contacts anyone or applies anywhere.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402


def process(scored, new_job_ids=None, notify=True):
    """`scored`: opportunities carrying an `analysis`. `new_job_ids`: ids inserted
    this cycle (only these can raise NEW_HIGH_PRIORITY_JOB). Returns stats."""
    from scripts.intelligence import analysis_engine, company_intel, networking_engine
    stats = {"analyses_saved": 0, "networking": {"suggested": 0, "inserted": 0, "refreshed": 0}, "notifications": 0}
    if not scored:
        return stats
    for o in scored:
        if o.get("analysis"):
            analysis_engine.save_analysis(o["analysis"])
            stats["analyses_saved"] += 1

    lookup = company_intel.make_lookup(company_intel.build_company_index())
    contacts = storage.read_csv(paths.NETWORKING_CSV)
    actions = []
    for o in scored:
        if o.get("analysis"):
            actions += networking_engine.recommend_actions(o, o["analysis"], lookup(o.get("company")), contacts)
    inserted, refreshed = networking_engine.save_suggestions(actions)
    stats["networking"] = {"suggested": len(actions), "inserted": inserted, "refreshed": refreshed}

    if notify:
        from scripts.intelligence import notifications
        new_ids = set(new_job_ids) if new_job_ids is not None else {o.get("id") for o in scored}
        sent = notifications.notify_new_jobs([o for o in scored if o.get("id") in new_ids])
        stats["notifications"] = len(sent)
    return stats


def reanalyze(job_ids=None):
    """Re-runs the analysis for stored jobs with the ACTIVE model version (e.g. after
    approving a learning suggestion), from the evidence already in tracking/jobs.csv.
    Updates the analysis summary columns and history; never fetches anything."""
    from scripts.daily_research import JOBS_FIELDNAMES, SUB_SCORE_KEYS
    from scripts.intelligence import analysis_engine, career_data, company_intel, networking_engine
    rows = storage.read_csv(paths.JOBS_CSV)
    lookup = company_intel.make_lookup(company_intel.build_company_index())
    contacts = storage.read_csv(paths.NETWORKING_CSV)
    changed, actions = [], []
    for row in rows:
        if not row.get("id") or (job_ids and row["id"] not in job_ids):
            continue
        opp = career_data.to_opportunity(row)
        sr = opp["scoring_result"]
        explicit = ({k: sr[k] for k in SUB_SCORE_KEYS}
                    if sr.get("sub_scores_explicit") and all(sr.get(k) is not None for k in SUB_SCORE_KEYS) else None)
        a = analysis_engine.analyze(opp, company_lookup=lookup, contacts=contacts, explicit_sub_scores=explicit)
        before = (row.get("decision"), row.get("model_version"))
        row.update(decision=a["decision"], opportunity_score=a["opportunity_score"],
                   analysis_confidence=a["confidence"], model_version=a["model_version"])
        analysis_engine.save_analysis(a)
        actions += networking_engine.recommend_actions(opp, a, lookup(row.get("company")), contacts)
        changed.append({"id": row["id"], "job_title": row.get("job_title"), "before": before[0],
                        "after": a["decision"], "model_version": a["model_version"]})
    storage.write_csv(paths.JOBS_CSV, JOBS_FIELDNAMES, rows)
    networking_engine.save_suggestions(actions)
    return changed
