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
