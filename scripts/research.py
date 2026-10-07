#!/usr/bin/env python3
"""Research run orchestrator (Phase 3).

Wraps scripts.daily_research.run() (unchanged) with a persisted "research
snapshot" — run_id, timestamps, queries, providers, results, errors, and
source health — so provider/search/discovery performance can be analyzed
over time (daily/weekly trends, which provider actually finds things, which
queries are worth keeping). Does not reimplement or replace the pipeline;
it is a thin, additive wrapper the `career_hunter.py research` CLI command uses.
"""
import argparse
import datetime as _dt
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import daily_research  # noqa: E402
from scripts.lib import paths  # noqa: E402

SNAPSHOT_FIELDS_HELP = (
    "run_id, started_at, completed_at, queries, providers, results_count, "
    "new_jobs, duplicates, errors, source_health, status"
)


def _determine_status(stats, source_health):
    if not source_health:
        return "FAILED"
    any_available = any(h.get("status") in ("SUCCESS", "EMPTY") for h in source_health)
    any_failed = any(h.get("status") in ("UNAVAILABLE", "ERROR") for h in source_health)
    if stats.get("number_new", 0) > 0:
        return "SUCCESS"
    if any_available and not stats.get("number_collected"):
        return "SUCCESS"  # reached sources fine, genuinely nothing new to report
    if any_failed and not any_available:
        return "FAILED"
    return "PARTIAL"


def run_research(region=None, remote=False, freelance=False, source_filter=None, limit=None, dry_run=False,
                 employment_types=None, mode=None):
    """Runs one research cycle via scripts.daily_research.run() and persists
    a research snapshot to data/research_runs/<run_id>.json. Returns the
    snapshot dict (plus the underlying pipeline result under "pipeline_result").
    mode/employment_types: Phase 4.1/4.2 career search mode (optional;
    snapshots without a "mode" key — every pre-4.2 snapshot — still load).
    """
    run_id = uuid.uuid4().hex[:12]
    started_at = _dt.datetime.now().isoformat(timespec="seconds")

    result = daily_research.run(region=region, remote=remote, freelance=freelance,
                                 source_filter=source_filter, limit=limit, dry_run=dry_run,
                                 employment_types=employment_types, mode=mode)
    completed_at = _dt.datetime.now().isoformat(timespec="seconds")

    if result["dry_run"]:
        snapshot = {
            "run_id": run_id, "started_at": started_at, "completed_at": completed_at,
            "queries": result["query_summary"], "providers": [], "results_count": 0,
            "new_jobs": 0, "duplicates": 0, "errors": [], "source_health": [],
            "status": "DRY_RUN", "mode": mode,
        }
        return {**snapshot, "pipeline_result": result}

    stats = result["stats"]
    source_health = result["source_health"]
    errors = [{"source": h["source"], "error": h.get("error")} for h in source_health if h.get("error")]

    snapshot = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "queries": result.get("query_summary", {}),
        "providers": {
            "attempted": stats.get("sources_attempted", []),
            "successful": stats.get("sources_successful", []),
            "failed": stats.get("sources_failed", []),
        },
        "results_count": stats.get("number_collected", 0),
        "new_jobs": stats.get("number_new", 0),
        "duplicates": stats.get("number_duplicates", 0),
        "errors": errors,
        "source_health": source_health,
        "status": _determine_status(stats, source_health),
        "mode": mode,
        "exceptional_count": sum(1 for o in result.get("scored", []) if o.get("exceptional_opportunity")),
    }

    paths.DATA_RESEARCH_RUNS.mkdir(parents=True, exist_ok=True)
    out_path = paths.DATA_RESEARCH_RUNS / f"{run_id}.json"
    out_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")

    return {**snapshot, "pipeline_result": result, "snapshot_path": str(out_path)}


def load_research_runs():
    """All persisted research snapshots, oldest first — for trend analysis."""
    if not paths.DATA_RESEARCH_RUNS.exists():
        return []
    runs = []
    for f in sorted(paths.DATA_RESEARCH_RUNS.glob("*.json")):
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return runs


def print_research_summary(snapshot):
    """Clear CLI reporting (Phase 3 §17) — every field is printed, nothing
    about a failure is hidden.
    """
    mode = snapshot.get("mode")
    print(f"Research run {snapshot['run_id']} — status: {snapshot['status']}" + (f" — mode: {mode}" if mode else ""))
    if snapshot["status"] == "DRY_RUN":
        print(f"  Dry run — {snapshot['queries']['total_queries']} queries would be generated; nothing executed.")
        return
    providers = snapshot["providers"]
    print(f"  Providers attempted:  {', '.join(providers['attempted']) or 'none'}")
    print(f"  Providers available:  {', '.join(providers['successful']) or 'none'}")
    print(f"  Providers unavailable: {', '.join(providers['failed']) or 'none'}")
    print(f"  Results found: {snapshot['results_count']}")
    print(f"  New opportunities: {snapshot['new_jobs']}")
    print(f"  Duplicates: {snapshot['duplicates']}")
    print(f"  Exceptional opportunities: {snapshot.get('exceptional_count', 0)}")
    if snapshot["errors"]:
        print("  Errors:")
        for e in snapshot["errors"]:
            print(f"    - {e['source']}: {e['error']}")
    else:
        print("  Errors: none")
    print(f"  Snapshot saved to: {snapshot.get('snapshot_path', '(not saved — dry run)')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=None)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--freelance", action="store_true")
    parser.add_argument("--source", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    snapshot = run_research(region=args.region, remote=args.remote, freelance=args.freelance,
                             source_filter=args.source, limit=args.limit, dry_run=args.dry_run)
    print_research_summary(snapshot)


if __name__ == "__main__":
    main()
