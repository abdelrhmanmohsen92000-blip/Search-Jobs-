#!/usr/bin/env python3
"""Career Search Modes Engine orchestrator (Phase 4.1).

Decides WHICH search mode(s) from config/career_state.yaml should run this
cycle, and with what employment-type query strategy — then hands off to the
existing scripts.daily_research.run() for everything downstream (query
generation, source routing, acquisition, normalization, dedup, scoring,
portfolio evidence, reporting). Never reimplements any of that.

    CAREER STATE -> CURRENT PRIMARY GOAL -> SEARCH MODES -> MODE PRIORITY ->
    SEARCH FREQUENCY -> MODE-SPECIFIC QUERY GENERATION -> SOURCE ROUTING ->
    JOB ACQUISITION -> NORMALIZATION -> SCORING
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import daily_research  # noqa: E402
from scripts.lib import career_state  # noqa: E402

PRIORITY_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def split_limit(modes, total_limit):
    """Splits a total query budget across modes proportional to priority
    (HIGH:MEDIUM:LOW = 3:2:1), so a low-priority mode never starves out the
    user's current primary goal, but still gets at least 1 if included at
    all. None (no total_limit) means every mode keeps its own default limit.
    """
    if not total_limit:
        return {m["name"]: None for m in modes}
    total_weight = sum(PRIORITY_WEIGHT.get(m["priority"], 1) for m in modes) or 1
    return {
        m["name"]: max(1, round(total_limit * PRIORITY_WEIGHT.get(m["priority"], 1) / total_weight))
        for m in modes
    }


def run_for_mode(mode, region=None, limit=None, dry_run=False, source_filter=None):
    """mode: one entry from scripts.lib.career_state.active_modes()."""
    result = daily_research.run(
        region=region, freelance=mode["freelance_only"], source_filter=source_filter,
        limit=limit, dry_run=dry_run,
        employment_types=mode["employment_types"] or None, mode=mode["name"],
    )
    if not dry_run:
        career_state.record_mode_run(mode["name"])
    return {"mode": mode["name"], "priority": mode["priority"], **result}


def run_due_modes(region=None, total_limit=None, dry_run=False, source_filter=None, force_all=False):
    """Runs every active mode that's due today, priority order, splitting
    total_limit proportionally. force_all=True runs every active mode
    regardless of due-ness (e.g. an on-demand full check).
    """
    modes = career_state.active_modes()
    due = modes if force_all else career_state.due_modes(modes)
    if not due:
        return {"modes_run": [], "results": [], "message": "No search modes due to run right now."}

    limits = split_limit(due, total_limit)
    results = [
        run_for_mode(mode, region=region, limit=limits[mode["name"]], dry_run=dry_run, source_filter=source_filter)
        for mode in due
    ]
    return {"modes_run": [m["name"] for m in due], "results": results}


def _print_result(result):
    if result.get("dry_run"):
        print(f"[{result['mode']}] (priority {result['priority']}) dry run — "
              f"{result['query_summary']['total_queries']} queries would be generated.")
    else:
        print(f"[{result['mode']}] (priority {result['priority']}) "
              f"{len(result['scored'])} opportunities scored this cycle — report: {result['report_path']}")


def print_career_state(state=None):
    state = state if state is not None else career_state.load_career_state()
    print(f"Current primary goal: {career_state.primary_goal(state)}")
    runs = career_state.load_mode_runs()
    due = {m["name"] for m in career_state.due_modes(career_state.active_modes(state), runs=runs)}
    for m in career_state.active_modes(state):
        status = "DUE" if m["name"] in due else f"last run {runs.get(m['name'], 'never')}"
        print(f"  - {m['name']}: priority={m['priority']} frequency={m['frequency']} "
              f"employment_types={m['employment_types']} freelance_only={m['freelance_only']} ({status})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Total query budget split across due modes by priority")
    parser.add_argument("--source", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="Run every active mode regardless of frequency due-ness")
    parser.add_argument("--mode", default=None, help="Run a single named mode regardless of due-ness")
    parser.add_argument("--show", action="store_true", help="Print current career state and exit")
    args = parser.parse_args()

    if args.show:
        print_career_state()
        return

    if args.mode:
        modes = {m["name"]: m for m in career_state.active_modes()}
        if args.mode not in modes:
            print(f"Mode '{args.mode}' is not an active mode in config/career_state.yaml. "
                  f"Active modes: {sorted(modes)}")
            return
        _print_result(run_for_mode(modes[args.mode], region=args.region, limit=args.limit,
                                    dry_run=args.dry_run, source_filter=args.source))
        return

    outcome = run_due_modes(region=args.region, total_limit=args.limit, dry_run=args.dry_run,
                             source_filter=args.source, force_all=args.all)
    if not outcome["modes_run"]:
        print(outcome["message"])
        return
    for result in outcome["results"]:
        _print_result(result)


if __name__ == "__main__":
    main()
