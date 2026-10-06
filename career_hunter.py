#!/usr/bin/env python3
"""AI Career Hunter — CLI entrypoint (V1.4).

Commands:
    search       [--region <key>|global] [--remote] [--freelance] [--source <name>] [--limit N] [--dry-run]
    score        <technical> <experience> <software> <project> <location> <eligibility> <career_value> <compensation>
    companies    --from-json <file> | --list-hidden
    networking   --from-json <file> | --generate-queue
    applications --list | --list-pending
    daily        [--region ...] [--remote] [--freelance] [--source <name>] [--limit N] [--dry-run]
    weekly
    report       alias for `daily` followed by `weekly`
    web-search   [--region <key>|global] [--remote] [--freelance] [--dry-run]   (Web Intelligence Layer)
    browser-queue [--region <key>|global] [--remote] [--freelance]
    web-import   --file <path> | --directory <path> [--dry-run]
    analyze      [--score-min N] [--deep]          (AI job analysis + decisions, no report/alerts write)
    decision     [--score-min N]                    (decision engine only, prints decisions)
    strategy                                         (career strategy report)
    learning                                         (response/interview/offer rates by segment, with sample sizes)
    market                                           (market intelligence: demand signals with sample size)
    alerts                                           (generate reports/alerts.md from current tracking data)
    intelligence [--score-min N] [--deep]           (full pipeline: LOAD->ANALYZE->DECIDE->NETWORK->APPLY->REPORT->LEARN)
    research     [--region ...] [--remote] [--freelance] [--source <name>] [--limit N] [--dry-run]  (Phase 3: persisted research-run snapshot)
    company-sources --add <name> --url <url> [--source-type <type>] | --list | --run

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
    python career_hunter.py web-search --region global --dry-run
    python career_hunter.py browser-queue --region global
    python career_hunter.py web-import --file data/raw/search_results/linkedin.json
    python career_hunter.py web-import --directory data/raw/search_results/
    python career_hunter.py analyze --score-min 70
    python career_hunter.py analyze --score-min 85 --deep
    python career_hunter.py decision
    python career_hunter.py learning
    python career_hunter.py market
    python career_hunter.py intelligence --score-min 70
    python career_hunter.py research --region gulf
    python career_hunter.py company-sources --add "Acme Architects" --url https://acme.example/careers --source-type architecture_firm
    python career_hunter.py company-sources --list
    python career_hunter.py company-sources --run

V1.4 never sends emails, never sends LinkedIn messages, never applies
automatically, and never automates browser actions — human approval remains
mandatory for every outward action (see README "LinkedIn / human-approval policy").
"""
import argparse
import json

from scripts import company_intelligence, networking_intelligence  # noqa: F401
from scripts import career_intelligence, daily_research, research, search_config, weekly_analysis, web_research
from scripts import career_search_modes
from scripts.intelligence import career_strategy as career_strategy_lib
from scripts.intelligence import learning_engine as learning_engine_lib
from scripts.lib import paths, storage
from scripts.sources import company_careers as company_careers_lib
from scripts.web import browser_queue as browser_queue_lib
from scripts.web import search_engine as search_engine_lib


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


def cmd_web_search(args):
    """Web Intelligence Layer: generate the search plan; since no live search
    API or browser-automation session is configured in this environment,
    this NEVER pretends to have searched — it reports SEARCH_PROVIDER_UNAVAILABLE
    and (unless --dry-run) writes the browser queue so a human can run the
    searches manually and feed results back via `web-import`.
    """
    plan = search_config.build_query_plan(region=args.region, remote_only=args.remote, freelance_only=args.freelance)
    summary = search_config.summarize_plan(plan)

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "search_plan_queries": summary["total_queries"],
            "geographic_coverage": summary["region_rank_order"],
            "provider_status": "SEARCH_PROVIDER_UNAVAILABLE",
            "note": "No search API or browser session configured in this environment. "
                    "No trackers, reports, or opportunity data were touched.",
        }, indent=2))
        return

    results = search_engine_lib.run_web_search(plan[:1] or [None], provider=None)
    tasks = browser_queue_lib.build_browser_queue(region=args.region, remote_only=args.remote, freelance_only=args.freelance)
    queue_path = browser_queue_lib.generate_browser_queue_report(tasks)

    print(json.dumps({
        "provider_status": results[0].status,
        "error": results[0].error,
        "search_plan_queries": summary["total_queries"],
        "browser_queue_tasks": len(tasks),
        "browser_queue_report": str(queue_path),
        "next_step": "Run the queries in reports/browser_search_queue.md manually, export results to "
                     "data/raw/search_results/, then run `python career_hunter.py web-import --directory "
                     "data/raw/search_results/`.",
    }, indent=2))


def cmd_browser_queue(args):
    tasks = browser_queue_lib.build_browser_queue(region=args.region, remote_only=args.remote, freelance_only=args.freelance)
    out = browser_queue_lib.generate_browser_queue_report(tasks)
    print(f"Browser search queue written to {out} ({len(tasks)} tasks)")


def cmd_web_import(args):
    from pathlib import Path
    directory = Path(args.directory) if args.directory else None
    result = web_research.run_web_import(directory=directory, file_path=args.file, dry_run=args.dry_run)
    if result["dry_run"]:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result["stats"], indent=2, default=str))


def _print_enriched_summary(enriched, label="Analyzed"):
    print(f"{label} {len(enriched)} opportunities.")
    for o in enriched[:10]:
        d = o["decision"]
        print(f"  [{o['action_priority']:.1f}] {d['decision']:16s} {o.get('job_title')} @ {o.get('company')} "
              f"(match={o.get('match_score')}, ai={o['job_analysis']['ai_opportunity_score']})")


def cmd_analyze(args):
    enriched = career_intelligence.analyze_opportunities(score_min=args.score_min, deep=args.deep)
    _print_enriched_summary(enriched)


def cmd_decision(args):
    enriched = career_intelligence.analyze_opportunities(score_min=args.score_min)
    career_intelligence.record_decisions(enriched)
    for o in enriched:
        d = o["decision"]
        print(json.dumps({
            "company": o.get("company"), "job_title": o.get("job_title"), "decision": d["decision"],
            "why": d["why"], "risks": d["risks"], "next_action": d["next_action"],
            "action_priority": o["action_priority"],
        }, indent=2))


def cmd_strategy(args):
    report = career_strategy_lib.career_strategy_report()
    print(json.dumps(report, indent=2, default=str))


def cmd_learning(args):
    report = learning_engine_lib.full_learning_report()
    print(json.dumps(report, indent=2, default=str))


def cmd_market(args):
    report = career_strategy_lib.market_intelligence()
    print(json.dumps(report, indent=2, default=str))


def cmd_alerts(args):
    enriched = career_intelligence.analyze_opportunities()
    alerts = career_intelligence.generate_alerts(enriched)
    out = career_intelligence.generate_alerts_report(alerts)
    print(f"Alerts report written to {out} ({len(alerts)} alert(s)).")


def cmd_intelligence(args):
    """Full pipeline: LOAD -> ANALYZE -> SCORE -> DECIDE -> NETWORK -> APPLICATION STRATEGY -> REPORT -> LEARN.
    Never sends anything, never applies anything, never automates LinkedIn/browser actions.
    """
    result = career_intelligence.run_intelligence_cycle(score_min=args.score_min, deep=args.deep)
    _print_enriched_summary(result["enriched"], label="Intelligence cycle analyzed")
    print(f"Report: {result['report_path']}")
    print(f"Alerts: {len(result['alerts'])} (see reports/alerts.md)")


def cmd_research(args):
    """Phase 3: runs one research cycle and persists a research-run snapshot
    (data/research_runs/<run_id>.json) for later trend analysis. Clearly
    reports which providers are available/unavailable — never hides a failure.
    """
    snapshot = research.run_research(region=args.region, remote=args.remote, freelance=args.freelance,
                                      source_filter=args.source, limit=args.limit, dry_run=args.dry_run)
    research.print_research_summary(snapshot)


def cmd_career_state(args):
    if args.show:
        career_search_modes.print_career_state()
        return
    if args.mode:
        modes = {m["name"]: m for m in career_search_modes.career_state.active_modes()}
        if args.mode not in modes:
            print(f"Mode '{args.mode}' is not an active mode in config/career_state.yaml. "
                  f"Active modes: {sorted(modes)}")
            return
        result = career_search_modes.run_for_mode(modes[args.mode], region=args.region, limit=args.limit,
                                                    dry_run=args.dry_run, source_filter=args.source)
        career_search_modes._print_result(result)
        return
    outcome = career_search_modes.run_due_modes(region=args.region, total_limit=args.limit, dry_run=args.dry_run,
                                                 source_filter=args.source, force_all=args.all)
    if not outcome["modes_run"]:
        print(outcome["message"])
        return
    for result in outcome["results"]:
        career_search_modes._print_result(result)


def cmd_company_sources(args):
    if args.add:
        if not args.url:
            print("--url is required with --add (use the company's real, verified careers URL).")
            return
        row = company_careers_lib.add_company_source(
            args.add, args.url, source_type=args.source_type or "",
            region=args.region or "UNKNOWN", priority=args.priority or "MEDIUM",
        )
        print(f"Added: {row['company']} -> {row['career_url']} (region={row['region']}, priority={row['priority']})")
    elif args.list:
        rows = company_careers_lib.load_company_sources()
        if not rows:
            print("No company career pages configured yet. See config/company_career_pages.example.yaml, "
                  "then `company-sources --add` with a real, verified URL.")
        for r in rows:
            print(f"{r['company']} ({r.get('source_type', '')}) — {r['career_url']} "
                  f"[region={r.get('region', 'UNKNOWN')}, priority={r.get('priority', 'MEDIUM')}, "
                  f"enabled={r.get('enabled')}, last_status={r.get('last_status') or 'never checked'}]")
    elif args.run:
        results = company_careers_lib.run_configured_company_sources(limit=args.limit)
        if not results:
            print("No enabled company career pages to check.")
        for r in results:
            print(f"{r.source}: {r.status}" + (f" — {r.error}" if r.error else ""))
    else:
        print("Nothing to do. Use --add <name> --url <url>, --list, or --run.")


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

    p_web_search = sub.add_parser("web-search", help="Web Intelligence Layer: generate search plan + browser queue (no live provider)")
    add_region_flags(p_web_search)
    p_web_search.add_argument("--dry-run", action="store_true")
    p_web_search.set_defaults(func=cmd_web_search)

    p_browser_queue = sub.add_parser("browser-queue", help="Generate reports/browser_search_queue.md")
    add_region_flags(p_browser_queue)
    p_browser_queue.set_defaults(func=cmd_browser_queue)

    p_web_import = sub.add_parser("web-import", help="Import search results from data/raw/search_results/")
    p_web_import.add_argument("--file", default=None, help="A single search-results JSON file")
    p_web_import.add_argument("--directory", default=None, help="A directory of search-results JSON files")
    p_web_import.add_argument("--dry-run", action="store_true")
    p_web_import.set_defaults(func=cmd_web_import)

    p_analyze = sub.add_parser("analyze", help="AI job analysis + decisions (V1.4)")
    p_analyze.add_argument("--score-min", type=float, default=0)
    p_analyze.add_argument("--deep", action="store_true")
    p_analyze.set_defaults(func=cmd_analyze)

    p_decision = sub.add_parser("decision", help="Decision engine only; records to tracking/decisions.csv")
    p_decision.add_argument("--score-min", type=float, default=0)
    p_decision.set_defaults(func=cmd_decision)

    p_strategy = sub.add_parser("strategy", help="Career strategy report (best countries/titles/companies/sources)")
    p_strategy.set_defaults(func=cmd_strategy)

    p_learning = sub.add_parser("learning", help="Response/interview/offer rates by segment, with sample sizes")
    p_learning.set_defaults(func=cmd_learning)

    p_market = sub.add_parser("market", help="Market intelligence: demand signals with sample size")
    p_market.set_defaults(func=cmd_market)

    p_alerts = sub.add_parser("alerts", help="Generate reports/alerts.md from current tracking data")
    p_alerts.set_defaults(func=cmd_alerts)

    p_intelligence = sub.add_parser("intelligence", help="Full V1.4 pipeline: LOAD->ANALYZE->DECIDE->NETWORK->APPLY->REPORT->LEARN")
    p_intelligence.add_argument("--score-min", type=float, default=0)
    p_intelligence.add_argument("--deep", action="store_true")
    p_intelligence.set_defaults(func=cmd_intelligence)

    p_research = sub.add_parser("research", help="Run one research cycle and persist a research-run snapshot (Phase 3)")
    add_region_flags(p_research)
    p_research.add_argument("--dry-run", action="store_true")
    p_research.set_defaults(func=cmd_research)

    p_career_state = sub.add_parser("career-state", help="Career Search Modes Engine (Phase 4.1)")
    p_career_state.add_argument("--show", action="store_true", help="Print current primary goal + active modes and exit")
    p_career_state.add_argument("--mode", default=None, help="Run a single named mode regardless of due-ness")
    p_career_state.add_argument("--region", default=None)
    p_career_state.add_argument("--limit", type=int, default=None, help="Total query budget split across due modes by priority")
    p_career_state.add_argument("--source", default=None)
    p_career_state.add_argument("--dry-run", action="store_true")
    p_career_state.add_argument("--all", action="store_true", help="Run every active mode regardless of frequency due-ness")
    p_career_state.set_defaults(func=cmd_career_state)

    p_company_sources = sub.add_parser("company-sources", help="Manage first-class company career-page sources (Phase 3)")
    p_company_sources.add_argument("--add", metavar="COMPANY_NAME", default=None)
    p_company_sources.add_argument("--url", default=None, help="The company's real, verified careers URL (required with --add)")
    p_company_sources.add_argument("--source-type", default=None)
    p_company_sources.add_argument("--region", default=None, help="Verified region/country for this company (UNKNOWN if not yet confirmed)")
    p_company_sources.add_argument("--priority", default=None, choices=["HIGH", "MEDIUM", "LOW"],
                                    help="Starting company-fit priority hint (Phase 4) — a human judgment, never computed")
    p_company_sources.add_argument("--list", action="store_true")
    p_company_sources.add_argument("--run", action="store_true", help="Check every enabled configured company career page")
    p_company_sources.add_argument("--limit", type=int, default=None, help="Cap how many companies are checked this run (HIGH priority first)")
    p_company_sources.set_defaults(func=cmd_company_sources)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
