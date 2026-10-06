#!/usr/bin/env python3
"""AI Career Hunter — CLI entrypoint (V1.2).

Commands:
    search       [--region <key>|global] [--remote] [--freelance] [--source <name>] [--limit N] [--dry-run]
    score        <technical> <experience> <software> <project> <location> <eligibility> <career_value> <compensation>
    companies    --from-json <file> | --list-hidden
    networking   --from-json <file> | --generate-queue
    applications --list | --list-pending
    daily        [--region ...] [--remote] [--freelance] [--source <name>] [--limit N] [--dry-run]
    weekly
    report       alias for `daily` followed by `weekly`

Examples:
    python career_hunter.py search --region global
    python career_hunter.py search --region gulf
    python career_hunter.py search --region europe
    python career_hunter.py search --region north_america
    python career_hunter.py search --remote
    python career_hunter.py search --freelance
    python career_hunter.py search --region global --dry-run
    python career_hunter.py daily --region global
    python career_hunter.py daily --region global --dry-run
    python career_hunter.py weekly
"""
import argparse
import json

from scripts import company_intelligence, networking_intelligence  # noqa: F401
from scripts import daily_research, search_config, weekly_analysis
from scripts.lib import paths, storage


def cmd_search(args):
    if args.dry_run:
        plan = search_config.build_query_plan(
            region=args.region, remote_only=args.remote, freelance_only=args.freelance,
            include_browser_required=not args.no_browser_required, source_filter=args.source, limit=args.limit,
        )
        summary = search_config.summarize_plan(plan)
        print(json.dumps({
            "dry_run": True,
            "geographic_coverage": summary["region_rank_order"],
            "expected_search_volume": summary["total_queries"],
            "enabled_sources": sorted({q["source"] for q in plan}),
            "search_matrix_titles": summary["distinct_titles"],
            "note": "No trackers, reports, or opportunity data were touched.",
        }, indent=2))
        return

    plan = search_config.build_query_plan(
        region=args.region, remote_only=args.remote, freelance_only=args.freelance,
        include_browser_required=not args.no_browser_required, source_filter=args.source, limit=args.limit,
    )
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(json.dumps(search_config.summarize_plan(plan), indent=2))


def cmd_score(args):
    from scripts.lib.scoring import action_for_result, compute_weighted_score, priority_for_score, recommendation_for_score

    order = ["technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation"]
    sub_scores = dict(zip(order, args.values))
    score = compute_weighted_score(sub_scores)
    print(json.dumps({
        "score": score,
        "priority": priority_for_score(score),
        "recommendation": recommendation_for_score(score),
        "action": action_for_result(score, sub_scores),
    }, indent=2))


def cmd_companies(args):
    if args.from_json:
        data = json.loads(open(args.from_json, encoding="utf-8").read())
        records = [data] if isinstance(data, dict) else data
        for raw in records:
            rec = company_intelligence.add_company(raw)
            print(f"Added: {rec['company_name']} -> {rec['category']} (fit={rec['ai_fit_score']})")
    elif args.list_hidden:
        for c in company_intelligence.hidden_opportunities():
            print(f"{c['company_name']} ({c.get('country', '?')}) fit={c.get('ai_fit_score')}")
    elif args.list:
        for c in company_intelligence.load_companies():
            print(f"{c['company_name']} ({c.get('country', '?')}) {c.get('category')} fit={c.get('ai_fit_score')}")
    else:
        print("Nothing to do. Use --from-json <file>, --list-hidden, or --list.")


def cmd_networking(args):
    if args.from_json:
        data = json.loads(open(args.from_json, encoding="utf-8").read())
        records = [data] if isinstance(data, dict) else data
        for raw in records:
            rec = networking_intelligence.add_contact(raw)
            print(f"Added: {rec['person']} ({rec['role']} @ {rec['company']}) -> priority {rec['priority']}")
    if args.generate_queue or args.from_json:
        out = networking_intelligence.generate_networking_queue()
        print(f"Networking queue written to {out}")
    if not args.from_json and not args.generate_queue:
        print("Nothing to do. Use --from-json <file> or --generate-queue.")


def cmd_applications(args):
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    if args.list_pending:
        applications = [a for a in applications if a.get("status") not in ("REJECTED", "CLOSED", "ACCEPTED", "")]
    if not applications:
        print("No applications logged in tracking/applications.csv.")
        return
    for a in applications:
        print(f"{a.get('job_title')} @ {a.get('company')} — {a.get('status')} (score {a.get('score')})")


def cmd_daily(args):
    result = daily_research.run(region=args.region, remote=args.remote, freelance=args.freelance,
                                 source_filter=args.source, limit=args.limit, dry_run=args.dry_run)
    if result["dry_run"]:
        print(json.dumps(result["query_summary"], indent=2))
        print(f"(dry run — {result['query_summary']['total_queries']} queries would be generated; "
              f"no trackers or reports were modified)")
    else:
        print(f"Daily report written to {result['report_path']} ({len(result['scored'])} opportunities scored this cycle)")


def cmd_weekly(args):
    analysis = weekly_analysis.analyze()
    out = weekly_analysis.generate_weekly_report(analysis)
    strategy_out = weekly_analysis.generate_weekly_strategy(analysis)
    print(f"Weekly report written to {out}")
    print(f"Weekly strategy written to {strategy_out}")


def cmd_report(args):
    cmd_daily(args)
    cmd_weekly(args)


def build_parser():
    parser = argparse.ArgumentParser(prog="career_hunter.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_region_flags(p):
        p.add_argument("--region", default=None, help="Region key, or 'global'/'worldwide'/'all'")
        p.add_argument("--remote", action="store_true")
        p.add_argument("--freelance", action="store_true")
        p.add_argument("--source", default=None, help="Restrict to a single source by name")
        p.add_argument("--limit", type=int, default=None, help="Cap results/queries generated")

    p_search = sub.add_parser("search", help="Build and display the search query plan")
    add_region_flags(p_search)
    p_search.add_argument("--no-browser-required", action="store_true")
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--dry-run", action="store_true", help="Show coverage/volume only; touch no files")
    p_search.set_defaults(func=cmd_search)

    p_score = sub.add_parser("score", help="Score a single opportunity from 8 sub-scores (0-10 each)")
    p_score.add_argument("values", nargs=8, type=float,
                          metavar=("technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation"))
    p_score.set_defaults(func=cmd_score)

    p_companies = sub.add_parser("companies", help="Add/list companies (company intelligence engine)")
    p_companies.add_argument("--from-json")
    p_companies.add_argument("--list-hidden", action="store_true")
    p_companies.add_argument("--list", action="store_true")
    p_companies.set_defaults(func=cmd_companies)

    p_networking = sub.add_parser("networking", help="Add contacts / generate the networking queue")
    p_networking.add_argument("--from-json")
    p_networking.add_argument("--generate-queue", action="store_true")
    p_networking.set_defaults(func=cmd_networking)

    p_applications = sub.add_parser("applications", help="List the application tracker")
    p_applications.add_argument("--list-pending", action="store_true")
    p_applications.set_defaults(func=cmd_applications)

    p_daily = sub.add_parser("daily", help="Run a full daily research cycle")
    add_region_flags(p_daily)
    p_daily.add_argument("--dry-run", action="store_true", help="Generate queries only; touch no trackers/reports")
    p_daily.set_defaults(func=cmd_daily)

    p_weekly = sub.add_parser("weekly", help="Generate the weekly intelligence report + strategy")
    p_weekly.set_defaults(func=cmd_weekly)

    p_report = sub.add_parser("report", help="Run daily cycle then weekly rollup")
    add_region_flags(p_report)
    p_report.add_argument("--dry-run", action="store_true")
    p_report.set_defaults(func=cmd_report)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
