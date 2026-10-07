"""Synthetic demo workspace (V1.3+).

Loads fixtures/synthetic_jobs.json through the REAL pipeline
(normalize -> dedup -> analysis -> decision -> jobs.csv -> networking ->
notifications) into an ISOLATED workspace, never the real trackers:

    python career_hunter.py demo                       # -> ./demo_workspace
    python career_hunter.py --workspace demo_workspace dashboard

Every demo job is labelled SYNTHETIC (company names start with "[SYNTHETIC]",
source SYNTHETIC_DEMO, URLs on synthetic.example). Relative dates in the
fixture are resolved against today so freshness is meaningful.

--with-activity additionally simulates a few pipeline moves (shortlist,
apply, interview, a rejection) so the dashboard funnel has something to show;
those events carry the actor `human:demo-simulation`.
"""
import datetime as _dt
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import paths, storage  # noqa: E402

FIXTURE_PATH = paths.ROOT / "fixtures" / "synthetic_jobs.json"
DEFAULT_WORKSPACE = paths.ROOT / "demo_workspace"


def load_fixture_records(today=None, path=None):
    today = today or _dt.date.today()
    data = json.loads(Path(path or FIXTURE_PATH).read_text(encoding="utf-8"))
    records = []
    for j in data["jobs"]:
        r = dict(j)
        posted = r.pop("posted_days_ago", None)
        if posted is not None:
            r["date_posted"] = (today - _dt.timedelta(days=int(posted))).isoformat()
        closing = r.pop("closing_in_days", None)
        if closing:
            r["closing_date"] = (today + _dt.timedelta(days=int(closing))).isoformat()
        r.pop("synthetic", None)
        r["date_found"] = today.isoformat()
        r.setdefault("provenance", {"source": r.get("source"), "source_url": r.get("source_url"),
                                    "retrieved_at": today.isoformat(), "extraction_method": "SYNTHETIC_FIXTURE",
                                    "confidence": 90})
        records.append(r)
    return records


def init_workspace(workspace):
    """Creates tracking/ with the real trackers' headers (no rows)."""
    workspace = Path(workspace)
    (workspace / "tracking").mkdir(parents=True, exist_ok=True)
    model = workspace / "config" / "scoring_model.yaml"
    if not model.exists():  # learning approvals in the demo change this copy, never the real model
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text((paths.CONFIG_DIR / "scoring_model.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    for f in (paths.ROOT / "tracking").glob("*.csv"):
        target = workspace / "tracking" / f.name
        if not target.exists():
            with open(f, encoding="utf-8") as src:
                target.write_text(src.readline(), encoding="utf-8")
    return workspace


def seed(workspace=None, with_activity=False, reset=False, echo=False):
    """Seeds the demo workspace and leaves `paths` pointing at it. Returns stats."""
    from scripts import daily_research
    from scripts.intelligence import post_research
    workspace = Path(workspace or DEFAULT_WORKSPACE).resolve()
    if workspace == paths.ROOT.resolve():
        raise ValueError("Refusing to seed synthetic data into the repository's real workspace")
    if reset and workspace.exists():
        shutil.rmtree(workspace)
    init_workspace(workspace)
    paths.use_workspace(workspace)
    previous_mode = os.environ.get("NETWORK_MODE")
    os.environ["NETWORK_MODE"] = "offline"  # the demo never touches the network
    try:
        records = load_fixture_records()
        scored, rejected, duplicates = daily_research.normalize_and_score(records)
        before = {r.get("id") for r in storage.read_csv(paths.JOBS_CSV)}
        inserted, updated = daily_research.upsert_jobs_rows([daily_research.opportunity_to_jobs_row(o) for o in scored])
        new_ids = {r.get("id") for r in storage.read_csv(paths.JOBS_CSV)} - before
        from scripts.intelligence import notifications
        notify_config = notifications.load_config()
        stats = {"workspace": str(workspace), "fixture_records": len(records), "jobs_inserted": inserted,
                 "jobs_updated": updated, "duplicates_merged": len(duplicates), "rejected": len(rejected)}
        if not echo:
            notify_config = {**notify_config, "channels": {**notify_config.get("channels", {}),
                                                           "terminal": {"enabled": False}}}
        stats["post_processing"] = _post(post_research, scored, new_ids, notify_config)
        stats["decisions"] = {}
        for o in scored:
            stats["decisions"][o["decision"]] = stats["decisions"].get(o["decision"], 0) + 1
        if with_activity:
            stats["activity"] = simulate_activity(scored)
        return stats
    finally:
        if previous_mode is None:
            os.environ.pop("NETWORK_MODE", None)
        else:
            os.environ["NETWORK_MODE"] = previous_mode


def _post(post_research, scored, new_ids, notify_config):
    from scripts.intelligence import notifications
    stats = post_research.process(scored, new_job_ids=new_ids, notify=False)
    stats["notifications"] = len(notifications.notify_new_jobs(
        [o for o in scored if o.get("id") in new_ids], config=notify_config, echo=False))
    return stats


def simulate_activity(scored, today=None):
    """A few clearly-labelled simulated moves so the funnel/board are not empty."""
    from scripts.intelligence import application_pipeline as ap
    today = today or _dt.date.today()
    ranked = sorted([o for o in scored if o["decision"] in ("APPLY_NOW", "APPLY", "NETWORK_FIRST", "REVIEW")],
                    key=lambda o: -o["opportunity_score"])
    actor = "human:demo-simulation"
    plan = [("SHORTLISTED", "READY", "APPLIED", "INTERVIEW"), ("SHORTLISTED", "READY", "APPLIED"),
            ("SHORTLISTED", "APPLIED", "REJECTED"), ("SHORTLISTED",)]
    moves = []
    for opp, steps in zip(ranked, plan):
        for i, status in enumerate(steps):
            when = today - _dt.timedelta(days=10 - 3 * i)
            note = "demo simulation" + ("; reason: missing GCC experience" if status == "REJECTED" else "")
            ap.transition(opp["id"], status, actor=actor, note=note, today=when)
            moves.append((opp["id"], status))
    return {"moves": len(moves), "actor": actor}
