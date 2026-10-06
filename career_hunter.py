#!/usr/bin/env python3
"""AI Career Hunter — CLI entrypoint.

Commands:
    search      --region <key> | --remote | --freelance : build & show the query plan
    score       <technical> <experience> <software> <project> <location> <eligibility> <career_value> <compensation>
    companies   --from-json <file> | --list-hidden
    networking  --from-json <file> | --generate-queue
    daily       [--region ...] [--remote] [--freelance] : run a full research cycle, write reports/daily_report.md
    weekly                                               : write reports/weekly_report.md
    report      alias for `daily` followed by `weekly`

Examples:
    python career_hunter.py search --region europe
    python career_hunter.py search --region gulf
    python career_hunter.py search --remote
    python career_hunter.py search --freelance
    python career_hunter.py daily --region gulf
    python career_hunter.py weekly
"""
import argparse
import json
import sys

from scripts import company_intelligence, networking_intelligence  # noqa: F401
from scripts import daily_research, search_config, weekly_analysis


def cmd_search(args):
    plan = search_config.build_query_plan(
        region=args.region, remote_only=args.remote, freelance_only=args.freelance, include_manual=not args.no_manual
    )
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(json.dumps(search_config.summarize_plan(plan), indent=2))


def cmd_score(args):
    from scripts.lib.scoring import compute_weighted_score, priority_for_score, recommendation_for_score

    order = ["technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation"]
    sub_scores = dict(zip(order, args.values))
    score = compute_weighted_score(sub_scores)
    print(json.dumps({
        "score": score,
        "priority": priority_for_score(score),
        "recommendation": recommendation_for_score(score),
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
    else:
        print("Nothing to do. Use --from-json <file> or --list-hidden.")


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


def cmd_daily(args):
    report_path, scored = daily_research.run(region=args.region, remote=args.remote, freelance=args.freelance)
    print(f"Daily report written to {report_path} ({len(scored)} opportunities scored this cycle)")


def cmd_weekly(args):
    analysis = weekly_analysis.analyze()
    out = weekly_analysis.generate_weekly_report(analysis)
    print(f"Weekly report written to {out}")


def cmd_report(args):
    cmd_daily(args)
    cmd_weekly(args)


def build_parser():
    parser = argparse.ArgumentParser(prog="career_hunter.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_region_flags(p):
        p.add_argument("--region", default=None)
        p.add_argument("--remote", action="store_true")
        p.add_argument("--freelance", action="store_true")

    p_search = sub.add_parser("search", help="Build and display the search query plan")
    add_region_flags(p_search)
    p_search.add_argument("--no-manual", action="store_true")
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_score = sub.add_parser("score", help="Score a single opportunity from 8 sub-scores (0-10 each)")
    p_score.add_argument("values", nargs=8, type=float,
                          metavar=("technical", "experience", "software", "project", "location", "eligibility", "career_value", "compensation"))
    p_score.set_defaults(func=cmd_score)

    p_companies = sub.add_parser("companies", help="Add/list companies (company intelligence engine)")
    p_companies.add_argument("--from-json")
    p_companies.add_argument("--list-hidden", action="store_true")
    p_companies.set_defaults(func=cmd_companies)

    p_networking = sub.add_parser("networking", help="Add contacts / generate the networking queue")
    p_networking.add_argument("--from-json")
    p_networking.add_argument("--generate-queue", action="store_true")
    p_networking.set_defaults(func=cmd_networking)

    p_daily = sub.add_parser("daily", help="Run a full daily research cycle")
    add_region_flags(p_daily)
    p_daily.set_defaults(func=cmd_daily)

    p_weekly = sub.add_parser("weekly", help="Generate the weekly intelligence report")
    p_weekly.set_defaults(func=cmd_weekly)

    p_report = sub.add_parser("report", help="Run daily cycle then weekly rollup")
    add_region_flags(p_report)
    p_report.set_defaults(func=cmd_report)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
