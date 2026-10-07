"""V1.4-V1.7 CLI commands, registered onto career_hunter.py's parser.

    jobs | job | company | application | skills | feedback | dashboard | config |
    schedule | notifications | demo   (+ extended: companies, applications,
    networking, market, learning, report daily|weekly)

Every command reads/writes the ACTIVE workspace (`--workspace` /
CAREER_HUNTER_WORKSPACE). None of them applies to a job, sends a message,
or contacts anyone.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import paths, runtime  # noqa: E402


def _msg(exc):
    return exc.args[0] if exc.args else str(exc)


def _where(v):
    return ", ".join(x for x in (v.get("city"), v.get("country")) if x and x != "UNKNOWN") or "location UNKNOWN"


def _job_line(v):
    return (f"{(v.get('decision_icon') or ' ')} {v.get('decision') or '-':<13} {num(v.get('opportunity_score')):>5} "
            f"{num(v.get('overall_match')):>5}  {v.get('status', ''):<11} {v['id']:<17} {v.get('job_title')} @ "
            f"{v.get('company')} — {_where(v)}")


def num(v, d=1):
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def _not_found(kind, ident):
    print(f"No {kind} matches {ident!r}. Use `career_hunter.py {kind}s` to list them (a unique id prefix works).")
    return 1


# --- jobs ------------------------------------------------------------------------------

def cmd_jobs(args):
    from scripts.intelligence import insights
    views = insights.job_views()
    rows = insights.filter_jobs(views, country=args.country, city=args.city, role=args.role, company=args.company,
                                min_score=args.min_score, employment_type=args.employment_type, remote=args.remote,
                                freshness=args.freshness, status=args.status, decision=args.decision, q=args.search,
                                sort=args.sort, desc=not args.asc)
    if args.active:
        rows = [v for v in rows if insights.is_active(v)]
    if args.json:
        print(json.dumps(rows[: args.limit], indent=2, default=str))
        return
    if not views:
        print("No jobs yet. Run `career_hunter.py research` (or `career_hunter.py demo` for synthetic demo data).")
        return
    print(f"{len(rows)} of {len(views)} jobs   (decision, opportunity, match, status, id, title)")
    for v in rows[: args.limit]:
        print(_job_line(v) + ("  [SYNTHETIC]" if v["synthetic"] and "[SYNTHETIC]" not in (v["company"] or "") else ""))


def cmd_job(args):
    from scripts.intelligence import application_pipeline as ap, career_data, networking_engine
    row = career_data.find_job(args.job_id)
    if row is None:
        return _not_found("job", args.job_id)
    a = career_data.analysis_for(row)
    if args.json:
        print(json.dumps(a, indent=2, default=str))
        return
    req, gap = a["requirements"], a["skills_gap"]
    status = ap.effective_status(row, ap.get_application(row["id"]))
    print(f"{a['decision_icon']} {a['decision']} — {row.get('job_title')} @ {row.get('company')}")
    print(f"   {_where(row)} · {row.get('employment_type') or 'UNKNOWN'} · status {status} · id {row['id']}")
    print(f"   Overall match {a['overall_match']} · Opportunity {a['opportunity_score']} · Confidence {a['confidence']} "
          f"· model {a['model_version']} ({a['sub_scores_source']})")
    print(f"   Job page: {row.get('job_page_url') or row.get('source_url') or 'UNKNOWN'}")
    print(f"   Apply at: {row.get('application_url') or 'UNKNOWN'} · deadline {row.get('closing_date') or 'UNKNOWN'} "
          f"· freshness {a['freshness']}")
    print("\nWHY"), [print(f"  + {r}") for r in a["reasons"]]
    print("RISKS"), [print(f"  - {r}") for r in a["risks"]]
    print(f"RECOMMENDATION\n  {a['recommendation']}")
    print("\nDIMENSIONS (0-100; application_difficulty: higher = harder)")
    for k, v in a["dimensions"].items():
        print(f"  {k:<24} {v:>5}  {'█' * int(v // 5)}")
    print("\nSKILLS GAP")
    print(f"  matched:      {', '.join(gap['matched']) or '—'}")
    print(f"  transferable: {', '.join(t['skill'] + ' (via ' + '/'.join(t['via']) + ')' for t in gap['transferable']) or '—'}")
    print(f"  missing:      {', '.join(gap['missing']) or '—'}")
    print(f"  preferred, not demonstrated: {', '.join(gap['preferred_missing']) or '—'}")
    print("\nREQUIREMENTS (source tag in brackets; UNKNOWN = not stated in the posting)")
    fs = req.get("field_sources") or {}
    for key in ("min_years_experience", "education", "certifications", "languages", "work_mode", "employment_type",
                "seniority", "salary", "benefits", "department", "application_method", "eligibility_barriers"):
        value = req.get(key)
        value = ", ".join(value) if isinstance(value, list) else value
        print(f"  {key:<22} {value if value not in (None, '', []) else 'UNKNOWN'}  [{fs.get(key, '')}]")
    actions = [x for x in networking_engine.load_actions() if x.get("job_id") == row["id"]]
    if actions:
        print("\nNETWORKING (drafts only — you send them yourself)")
        for x in actions:
            print(f"  [{x['priority']}] {x['contact_type']} · {x['status']} · {x['action_id']}\n      {x['reason']}")
    print(f"\nNext: `career_hunter.py application {row['id']}` for the application packet.")


# --- companies -------------------------------------------------------------------------

def cmd_company(args):
    from scripts.intelligence import company_intel, insights
    index = company_intel.build_company_index()
    rec = index.get(args.company_id) or index.get(company_intel.company_id(args.company_id))
    if rec is None:
        matches = [r for cid, r in index.items() if cid.startswith(args.company_id.lower())]
        rec = matches[0] if len(matches) == 1 else None
    if rec is None:
        return _not_found("company", args.company_id)
    if args.json:
        print(json.dumps(rec, indent=2, default=str))
        return
    print(f"{rec['grade']} {rec['grade_label']} — {rec['company']} (score {rec['company_score']}"
          f"{', manual override' if rec['manual_override'] else ''}) · id {rec['company_id']}")
    for k in ("industry", "size", "website", "careers_page", "hiring_trend", "average_match", "region_tier",
              "active_opportunities", "job_count", "target_priority"):
        print(f"  {k:<22} {rec[k] if rec[k] not in (None, '') else 'UNKNOWN'}")
    print(f"  {'countries':<22} {', '.join(rec['countries']) or 'UNKNOWN'}")
    print(f"  {'contacts':<22} {', '.join(c for c in rec['contacts'] if c) or 'none logged'}")
    if rec["notes"]:
        print(f"  {'notes':<22} {rec['notes']}")
    jobs = [v for v in insights.job_views() if v["company_id"] == rec["company_id"]]
    if jobs:
        print("\nJOBS")
        for v in jobs:
            print("  " + _job_line(v))


def companies_ranking(args):
    from scripts.intelligence import company_intel
    rows = company_intel.ranked(company_intel.build_company_index())
    if not rows:
        print("No companies yet.")
        return
    print(f"{'GRADE':<17} {'SCORE':>5} {'ACTIVE':>6} {'TREND':<18} COMPANY (id)")
    for c in rows[: args.limit or len(rows)]:
        print(f"{c['grade'] + ' ' + c['grade_label']:<17} {c['company_score']:>5} {c['active_opportunities']:>6} "
              f"{c['hiring_trend']:<18} {c['company']} ({c['company_id']}){' *override' if c['manual_override'] else ''}")


# --- applications ----------------------------------------------------------------------

def applications_board(args):
    from scripts.intelligence import application_pipeline as ap
    board = ap.board()
    closed = board.pop("_closed")
    for col, cards in board.items():
        print(f"\n{col} ({len(cards)})")
        for c in cards[:15]:
            extra = f" · follow-up {c['follow_up_date']}" if c["follow_up_date"] else ""
            print(f"  {c['job_id']:<17} {c['job_title']} @ {c['company']} · {c['decision'] or '-'} "
                  f"· opp {num(c['opportunity_score'])}{extra}")
    if closed:
        print(f"\nCLOSED / WITHDRAWN ({len(closed)})")
        for c in closed:
            print(f"  {c['job_id']:<17} {c['job_title']} @ {c['company']} · {c['status']}")
    due = ap.due_followups()
    if due:
        print(f"\nFOLLOW-UPS DUE: " + ", ".join(f"{a['job_title']} @ {a['company']} ({a['follow_up_date']})" for a in due))
    print("\nMove with: career_hunter.py application <JOB_ID> --status SHORTLISTED|READY|APPLIED|...")


def cmd_application(args):
    from scripts.intelligence import application_pipeline as ap, career_data
    row = career_data.find_job(args.job_id)
    job_id = row["id"] if row else args.job_id
    if row is None and ap.get_application(job_id) is None:
        return _not_found("job", args.job_id)
    if args.status:
        try:
            rec = ap.transition(job_id, args.status, actor="human:cli", note=args.note or "", force=args.force)
        except ValueError as exc:
            print(f"Not moved: {_msg(exc)}")
            return 1
        print(f"{job_id}: now {rec['status']}" + (f" · follow-up {rec['follow_up_date']}" if rec.get("follow_up_date") else ""))
    edits = {k: getattr(args, k) for k in ("interview_date", "cv_version", "portfolio_version", "contact_person",
                                          "follow_up_date") if getattr(args, k)}
    if edits:
        try:
            ap.update_fields(job_id, **edits)
        except (KeyError, ValueError) as exc:
            print(f"Not updated: {_msg(exc)}")
            return 1
        print(f"{job_id}: updated {', '.join(edits)}")
    if args.status or edits:
        return
    if row is None:
        print(json.dumps(ap.get_application(job_id), indent=2))
        return
    if args.write:
        out, _ = ap.write_packet(job_id)
        print(f"Packet written to {out}")
        return
    packet = ap.build_packet(job_id)
    if args.json:
        print(json.dumps(packet, indent=2, default=str))
        return
    print(ap.packet_markdown(packet))
    history = ap.history(job_id)
    if history:
        print("\n## Status history")
        for e in history:
            print(f"- {e['at']} {e['from_status']} -> {e['to_status']} ({e['actor']}){' — ' + e['note'] if e['note'] else ''}")


# --- networking ------------------------------------------------------------------------

def networking_v14(args):
    from scripts.intelligence import networking_engine as ne
    updates = [("approve", "APPROVED"), ("done", "DONE"), ("replied", "REPLIED"), ("no_response", "NO_RESPONSE"),
               ("dismiss", "DISMISSED")]
    for attr, status in updates:
        action_id = getattr(args, attr, None)
        if action_id:
            try:
                row = ne.update_status(action_id, status, note=args.note or "")
            except (KeyError, ValueError) as exc:
                print(f"Not updated: {_msg(exc)}")
                return 1
            print(f"{row['action_id']}: {row['status']}" + (f" · follow-up {row['follow_up_date']}" if row.get("follow_up_date") else ""))
            return
    if args.refresh:
        print(ne.refresh_from_jobs())
    actions = ne.load_actions()
    if args.show:
        a = next((x for x in actions if x["action_id"].startswith(args.show)), None)
        if not a:
            return _not_found("networking action", args.show)
        print(f"{a['contact_type']} @ {a['company']} for {a['target_role']} [{a['priority']}, {a['status']}]")
        print(f"Why:   {a['reason']}\nAngle: {a['outreach_angle']}\n\nDRAFT (review and send it yourself):\n{a['draft_message']}")
        return
    due, open_ = ne.due_followups(actions), ne.open_actions(actions)
    print("Networking — drafts only. Career Hunter never sends messages or connection requests.\n")
    if due:
        print(f"FOLLOW-UPS DUE ({len(due)})")
        for a in due:
            print(f"  {a['action_id']:<40} {a['contact_type']} @ {a['company']} (follow-up {a['follow_up_date']})")
    print(f"SUGGESTED ({len(open_)})")
    for a in open_[: args.limit or len(open_)]:
        print(f"  [{a['priority']:<6}] {a['action_id']:<40} {a['contact_type']} @ {a['company']} — {a['target_role']}")
    if not open_ and not due:
        print("  none — run `career_hunter.py networking --refresh` after research.")
    print("\nShow a draft: networking --show <ACTION_ID>   ·   after YOU send it: networking --done <ACTION_ID>")


# --- skills / market -------------------------------------------------------------------

def cmd_skills(args):
    from scripts.intelligence import insights
    s = insights.skills_intelligence()
    if args.json:
        print(json.dumps(s, indent=2, default=str))
        return
    print(f"Skills intelligence — {s['active_jobs']} active job(s)\n")
    print("PRIORITY LEARNING")
    for r in s["priority_learning"]:
        print(f"  {r['skill']:<26} {r['status']:<13} required in {r['required_in']}, preferred in {r['preferred_in']} "
              f"· avg opp {r['avg_opportunity']} · helps: {', '.join(r['unlocks'][:3]) or '—'}")
    if not s["priority_learning"]:
        print("  none")
    print("\nMOST DEMANDED — YOU HAVE")
    for r in s["matched"][:12]:
        print(f"  {r['skill']:<26} required in {r['required_in']}, preferred in {r['preferred_in']}")
    print("\nTRANSFERABLE: " + (", ".join(r["skill"] for r in s["transferable"]) or "—"))
    print("MISSING:      " + (", ".join(r["skill"] for r in s["missing"]) or "—"))


def market_v15(args):
    from scripts.intelligence import career_strategy, insights
    m = insights.market_intelligence()
    if args.json:
        m["demand_signals_v14"] = career_strategy.market_intelligence()
        print(json.dumps(m, indent=2, default=str))
        return
    print(f"Market — {m['total_jobs']} jobs tracked, {m['active_jobs']} active; remote share "
          f"{m['remote_share'] if m['remote_share'] is not None else 'UNKNOWN'}%\n")
    for s in m["signals"]:
        print(f"  • {s}")
    for title, key in (("BY COUNTRY", "by_country"), ("BY ROLE", "by_role"), ("BY COMPANY", "by_company"),
                       ("BY EMPLOYMENT TYPE", "by_employment_type"), ("OPPORTUNITY SCORES", "opportunity_distribution")):
        print(f"\n{title}")
        for k, v in m[key]:
            print(f"  {str(k)[:40]:<40} {v:>4}  {'█' * min(40, v)}")
    print("\nPOSTED SALARIES (stated in postings only)")
    for k, v in m["posted_salaries"].items():
        print(f"  {k:<14} n={v['n']} min {v['min']:g} median {v['median']:g} max {v['max']:g}")
    if not m["posted_salaries"]:
        print("  none posted")


# --- reports ---------------------------------------------------------------------------

def report_kind(args):
    from scripts.intelligence import briefs
    if args.kind == "daily":
        path, data = briefs.write_report("daily")
        print(briefs.render_daily_brief(data))
        print(f"\nSaved to {path}")
    else:
        for kind in ("weekly_market", "weekly_skills"):
            path, _ = briefs.write_report(kind)
            print(f"{kind.replace('_', ' ').title()} report written to {path}")
        from scripts import weekly_analysis
        analysis = weekly_analysis.analyze()
        print(f"Weekly report written to {weekly_analysis.generate_weekly_report(analysis)}")
        print(f"Weekly strategy written to {weekly_analysis.generate_weekly_strategy(analysis)}")


# --- feedback / learning ------------------------------------------------------------------

def cmd_feedback(args):
    from scripts.intelligence import feedback
    try:
        row, rec = feedback.record(args.kind, args.job_id, reason=args.reason or "", rating=args.rating,
                                   note=args.note or "")
    except (KeyError, ValueError) as exc:
        print(f"Not recorded: {_msg(exc)}")
        return 1
    print(f"Feedback recorded: {row['kind']} for {row['job_title']} @ {row['company']} "
          f"(system had recommended {row['decision_at_time'] or 'UNKNOWN'}, model {row['model_version'] or 'UNKNOWN'})")
    if rec:
        print(f"Application status: {rec['status']}")


def learning_v17(args):
    from scripts.intelligence import learning_engine, learning_loop
    if args.action == "approve":
        try:
            s, model = learning_loop.approve(args.suggestion_id, activate=args.activate, allow_synthetic=args.allow_synthetic)
        except (KeyError, ValueError) as exc:
            print(f"Not approved: {_msg(exc)}")
            return 1
        print(f"Approved {s['suggestion_id']}: model version {s['proposed_version']} created"
              + (" and ACTIVATED." if args.activate else ". Activate with `career_hunter.py config --model-version "
                 + s['proposed_version'] + "`."))
        return
    if args.action == "reject":
        try:
            s = learning_loop.reject(args.suggestion_id, reason=args.reason or "")
        except (KeyError, ValueError) as exc:
            print(f"Not rejected: {_msg(exc)}")
            return 1
        print(f"Rejected {s['suggestion_id']}.")
        return
    if args.action == "suggestions":
        items = learning_loop.load_suggestions()
        if not items:
            print("No learning suggestions yet.")
        for s in items:
            print(f"{s['suggestion_id']}  {s['status']:<17} {s['base_version']} -> {s['proposed_version']}  "
                  f"({s['outcomes_used']} outcomes{', SYNTHETIC' if s.get('includes_synthetic') else ''})")
            for r in s["rationale"]:
                print(f"    {r}")
        return
    if args.action == "evaluate":
        report = learning_loop.evaluate()
        print(f"{report['status']}: {report.get('message') or ''}")
        print(f"Outcomes: {report['outcomes']} labelled ({report['by_outcome']}), pending {report['pending']}, "
              f"model {report['model_version']}")
        for decision, r in sorted(report["by_decision"].items()):
            print(f"  {decision:<14} n={r['n']:<3} interview/offer rate {r['rate']}%")
        if report["top_rejection_reasons"]:
            print("Top rejection reasons: " + "; ".join(f"{k} ({v})" for k, v in report["top_rejection_reasons"]))
        if report.get("suggestion"):
            s = report["suggestion"]
            print(f"\nSUGGESTION {s['suggestion_id']} (model {s['base_version']} -> {s['proposed_version']}) — NOT applied:")
            for r in s["rationale"]:
                print(f"  {r}")
            print(f"Approve: career_hunter.py learning approve {s['suggestion_id']} [--activate]")
        return
    report = learning_engine.full_learning_report()  # legacy V1.4 segment rates
    report["learning_loop"] = {k: v for k, v in learning_loop.evaluate(save=False).items()
                               if k in ("status", "message", "outcomes", "min_outcomes")}
    print(json.dumps(report, indent=2, default=str))


# --- dashboard / config / schedule / notifications / demo -----------------------------------

def cmd_dashboard(args):
    from scripts.dashboard import server
    if args.check:
        from scripts.dashboard import api
        status, payload = api.handle("GET", "/api/overview")
        print(f"Dashboard API: HTTP {status}, {payload.get('tiles', {}).get('jobs', 0)} jobs in workspace {paths.WORKSPACE}")
        return 0 if status == 200 else 1
    server.serve(host=args.host, port=args.port, verbose=args.verbose)


def cmd_config(args):
    from scripts import scheduler
    from scripts.intelligence import scoring_model
    if args.model_version:
        try:
            scoring_model.set_active(args.model_version)
        except ValueError as exc:
            print(f"Not changed: {_msg(exc)}")
            return 1
        print(f"Active decision model is now version {args.model_version} ({scoring_model.default_path()}).")
        return
    problems = validate_config()
    if args.validate:
        print("Configuration OK" if not problems else "Configuration problems:\n  " + "\n  ".join(problems))
        return 1 if problems else 0
    data = scoring_model.load_all()
    print(f"Workspace:        {paths.WORKSPACE}{' (repository)' if paths.WORKSPACE == paths.ROOT else ''}")
    print(f"NETWORK_MODE:     {runtime.network_mode()}")
    print(f"Timezone:         {scheduler.timezone_name()}")
    print(f"Decision model:   {data.get('active_version')} of {', '.join(map(str, data.get('versions') or {}))} "
          f"({scoring_model.default_path()})")
    print("Environment (values are never printed):")
    for k, v in runtime.environment_status().items():
        print(f"  {k:<28} {v:<8} {runtime.ENVIRONMENT_VARIABLES[k]}")
    print(f"Config files:     {paths.CONFIG_DIR}")
    print("Validation:       " + ("OK" if not problems else f"{len(problems)} problem(s) — run `config --validate`"))


def validate_config():
    """Loads and checks every config file; returns a list of problems (empty = OK)."""
    import os

    import yaml
    from scripts import scheduler
    from scripts.intelligence import learning_loop, networking_engine, notifications, scoring_model
    from scripts.intelligence.requirements_extractor import load_taxonomy
    problems = []
    for f in sorted(paths.CONFIG_DIR.glob("*.yaml")):
        try:
            yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            problems.append(f"{f.name}: invalid YAML ({exc.__class__.__name__})")

    def unknown_contacts():
        cfg = networking_engine.load_config()
        return [f"unknown contact type {c!r}" for fam in cfg.get("role_family_contacts") or []
                for c in fam.get("contacts") or [] if c not in cfg["contact_types"]]
    checks = [
        ("scoring_model.yaml", lambda: scoring_model.validate_model(scoring_model.active_model())),
        ("schedules.yaml", lambda: [] if scheduler.jobs() and scheduler.timezone() else ["no jobs"]),
        ("skills_taxonomy.yaml", lambda: [] if load_taxonomy()["skills"] else ["no skills"]),
        ("notifications.yaml", lambda: [f"unknown event {e!r}" for e in notifications.load_config().get("events") or {}
                                        if e not in notifications.EVENT_TYPES]),
        ("networking.yaml", unknown_contacts),
        ("learning.yaml", lambda: [] if int(learning_loop.load_config().get("min_outcomes", 0)) > 0
                         else ["min_outcomes must be > 0"]),
    ]
    for name, check in checks:
        try:
            problems += [f"{name}: {err}" for err in check() or []]
        except Exception as exc:  # report, never crash the validator
            problems.append(f"{name}: {type(exc).__name__}: {exc}")
    raw_mode = (os.environ.get("NETWORK_MODE") or "local").strip().lower()
    if raw_mode not in runtime.NETWORK_MODES:
        problems.append(f"NETWORK_MODE={raw_mode!r} is not one of {', '.join(runtime.NETWORK_MODES)}")
    return problems


def cmd_schedule(args):
    from scripts import scheduler
    if args.action == "list":
        for r in scheduler.status():
            print(f"{r['id']:<26} {r['cron']:<14} {'on ' if r['enabled'] else 'off'} next {r['next_run'] or '-':<26} "
                  f"last {r['last_run'] or '-'} {r['last_status'] or ''}{'  DUE' if r['due'] else ''}")
        print(f"Timezone: {scheduler.timezone_name()} (override with CAREER_HUNTER_TIMEZONE)")
    elif args.action == "run-due":
        results = scheduler.run_due(dry_run=args.dry_run)
        if not results:
            print("Nothing due.")
        for r in results:
            print(f"{r['job']}: {r['status']} {json.dumps(r.get('summary'), default=str)}")
    elif args.action == "run":
        if not args.job:
            print("Usage: schedule run <JOB_ID>  (see `schedule list`)")
            return 1
        r = scheduler.run_job(args.job, dry_run=args.dry_run)
        print(f"{r['job']}: {r['status']} {json.dumps(r.get('summary'), default=str)}")
    elif args.action == "daemon":
        scheduler.daemon(interval_seconds=args.interval)
    elif args.action == "cron":
        print(scheduler.crontab_text(), end="")


def cmd_notifications(args):
    from scripts.intelligence import notifications
    if args.mark_read:
        print(f"Marked {notifications.mark_read()} notification(s) read.")
        return
    rows = notifications.load_notifications()
    rows = rows if args.all else [r for r in rows if str(r.get("read")) != "True"]
    if not rows:
        print("No unread notifications.")
    for r in rows[-args.limit:]:
        print(f"{r['created_at']} [{r['severity']}] {r['event_type']}: {r['title']} — {r['body']}")


def cmd_demo(args):
    from scripts import demo
    target = args.demo_workspace or getattr(args, "global_workspace", None) or demo.DEFAULT_WORKSPACE
    stats = demo.seed(target, with_activity=args.with_activity, reset=args.reset)
    print(json.dumps(stats, indent=2, default=str))
    ws = stats["workspace"]
    print(f"\nSynthetic demo workspace ready (offline, isolated from your real trackers). Try:\n"
          f"  python career_hunter.py --workspace {ws} jobs\n"
          f"  python career_hunter.py --workspace {ws} report daily\n"
          f"  python career_hunter.py --workspace {ws} dashboard")


# --- parser registration -----------------------------------------------------------------

def _job_filters(p):
    for name in ("country", "city", "role", "company", "employment-type", "freshness", "status", "decision"):
        p.add_argument(f"--{name}", default=None)
    p.add_argument("--remote", default=None, choices=["true", "false"])
    p.add_argument("--min-score", type=float, default=None, help="Minimum opportunity score")
    p.add_argument("--search", default=None)
    p.add_argument("--sort", default="opportunity_score",
                   choices=["opportunity_score", "overall_match", "confidence", "date_found", "date_posted", "company",
                            "job_title", "country"])
    p.add_argument("--asc", action="store_true")
    p.add_argument("--active", action="store_true", help="Only active (not skipped/closed/stale) jobs")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")


def register(sub):
    p = sub.add_parser("jobs", help="List analyzed jobs with filters and sorting (V1.4)")
    _job_filters(p)
    p.set_defaults(func=cmd_jobs)

    p = sub.add_parser("job", help="Full analysis of one job: decision, reasons, risks, dimensions, skills gap")
    p.add_argument("job_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_job)

    p = sub.add_parser("company", help="Company intelligence for one company (id, name or id prefix)")
    p.add_argument("company_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_company)

    p = sub.add_parser("application", help="Application packet / move one job through the pipeline")
    p.add_argument("job_id")
    p.add_argument("--status", default=None, help="DISCOVERED..CLOSED (APPLIED and later = you did it)")
    p.add_argument("--note", default=None)
    p.add_argument("--force", action="store_true", help="Reopen a REJECTED/WITHDRAWN/CLOSED application")
    p.add_argument("--interview-date", default=None)
    p.add_argument("--follow-up-date", default=None)
    p.add_argument("--cv-version", default=None)
    p.add_argument("--portfolio-version", default=None)
    p.add_argument("--contact-person", default=None)
    p.add_argument("--write", action="store_true", help="Write the packet to reports/packets/<id>.md")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_application)

    p = sub.add_parser("skills", help="Skills intelligence: demand, gaps, learning priorities")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_skills)

    p = sub.add_parser("feedback", help="Record an outcome: application|interview|rejection|offer|no_response|withdrawn|job")
    p.add_argument("kind", choices=["application", "interview", "rejection", "offer", "no_response", "no-response",
                                    "withdrawn", "job"])
    p.add_argument("job_id")
    p.add_argument("--reason", default=None)
    p.add_argument("--rating", default=None, choices=["good", "bad"], help="For `feedback job`")
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_feedback)

    p = sub.add_parser("dashboard", help="Start the local dashboard (http://127.0.0.1:8765)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--check", action="store_true", help="Check the API without starting a server")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("config", help="Show/validate configuration; switch the active decision model version")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--model-version", default=None, help="Make this decision-model version active (explicit approval)")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("schedule", help="Scheduler: list | run-due | run <job> | daemon | cron")
    p.add_argument("action", choices=["list", "run-due", "run", "daemon", "cron"])
    p.add_argument("job", nargs="?", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--interval", type=int, default=60, help="daemon: seconds between checks")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("notifications", help="Show notifications (unread by default)")
    p.add_argument("--all", action="store_true")
    p.add_argument("--mark-read", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_notifications)

    p = sub.add_parser("demo", help="Seed an isolated SYNTHETIC demo workspace through the real pipeline (offline)")
    p.add_argument("--workspace", dest="demo_workspace", default=None, help="Default: ./demo_workspace")
    p.add_argument("--with-activity", action="store_true", help="Also simulate a few pipeline moves")
    p.add_argument("--reset", action="store_true", help="Delete the demo workspace first")
    p.set_defaults(func=cmd_demo)
