"""Daily Career Brief and weekly reports (V1.5).

    daily_brief()          NEW JOBS, TOP OPPORTUNITIES, APPLY NOW, NETWORK FIRST,
                           APPLICATION FOLLOWUPS, INTERVIEWS, SOURCE HEALTH,
                           SKILLS GAPS, MARKET SIGNALS
    weekly_market_report() jobs by country / role / company, trends, posted salaries
    weekly_skills_report() demand, gaps, transferable skills, learning priorities

Written to reports/ as markdown (dated file + a stable "latest" file) and
returned as dicts for the dashboard. Built only from stored data — running a
report never makes a network request.
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths  # noqa: E402

TOP_N = 10


def _fmt_job(v):
    where = ", ".join(x for x in (v.get("city"), v.get("country")) if x and x != "UNKNOWN") or "location UNKNOWN"
    tag = " [SYNTHETIC]" if v.get("synthetic") and "[SYNTHETIC]" not in (v.get("company") or "") else ""
    return (f"{v.get('decision_icon') or ''} {v.get('decision')} · {v.get('job_title')} @ {v.get('company')}{tag} — "
            f"{where} · opportunity {v.get('opportunity_score')} · match {v.get('overall_match')} · `{v.get('id')}`")


def daily_brief(today=None, views=None):
    from scripts.intelligence import application_pipeline as ap, insights, networking_engine
    today = today or _dt.date.today()
    views = insights.job_views() if views is None else views
    active = [v for v in views if insights.is_active(v)]
    since = (today - _dt.timedelta(days=1)).isoformat()
    new = [v for v in views if (v["date_found"] or "") >= since]
    top = sorted(active, key=lambda v: -(v["opportunity_score"] or 0))[:TOP_N]
    not_started = ("DISCOVERED", "VERIFIED", "ANALYZED", "SHORTLISTED", "READY")
    apply_now = [v for v in active if v["decision"] == "APPLY_NOW" and v["status"] in not_started]
    network_first = [v for v in active if v["decision"] == "NETWORK_FIRST" and v["status"] in not_started]
    skills = insights.skills_intelligence(views)
    market = insights.market_intelligence(views, today=today)
    return {
        "date": today.isoformat(),
        "new_jobs": sorted(new, key=lambda v: -(v["opportunity_score"] or 0)),
        "top_opportunities": top,
        "apply_now": apply_now,
        "network_first": network_first,
        "application_followups": ap.due_followups(today=today),
        "networking_followups": networking_engine.due_followups(today=today),
        "open_networking_actions": len(networking_engine.open_actions()),
        "interviews": ap.upcoming_interviews(today=today),
        "source_health": insights.source_summary(),
        "skills_gaps": skills["priority_learning"][:5],
        "market_signals": market["signals"],
        "totals": {"jobs": len(views), "active": len(active), "synthetic": sum(1 for v in views if v["synthetic"])},
    }


def render_daily_brief(b):
    lines = [f"# Daily Career Brief — {b['date']}", "",
             f"{b['totals']['jobs']} jobs tracked, {b['totals']['active']} active."]
    if b["totals"]["synthetic"]:
        lines.append(f"**{b['totals']['synthetic']} of them are SYNTHETIC demo jobs** (not real postings).")

    def section(title, items, fmt, empty):
        lines.extend(["", f"## {title}"])
        lines.extend([f"- {fmt(i)}" for i in items] or [f"_{empty}_"])
    section("NEW JOBS (last 24h)", b["new_jobs"][:TOP_N], _fmt_job, "No new jobs since yesterday.")
    section("TOP OPPORTUNITIES", b["top_opportunities"], _fmt_job, "No active opportunities.")
    section("APPLY NOW", b["apply_now"], lambda v: _fmt_job(v) + f" — `career_hunter.py application {v['id']}`",
            "Nothing waiting in APPLY NOW.")
    section("NETWORK FIRST", b["network_first"], _fmt_job, "No NETWORK_FIRST opportunities.")
    section("APPLICATION FOLLOWUPS", b["application_followups"],
            lambda a: f"{a.get('job_title')} @ {a.get('company')} — applied {a.get('application_date') or 'UNKNOWN'}, "
                      f"follow-up due {a.get('follow_up_date')} (you send it)", "No follow-ups due.")
    if b["networking_followups"] or b["open_networking_actions"]:
        lines.append(f"- Networking: {len(b['networking_followups'])} follow-up(s) due, "
                     f"{b['open_networking_actions']} suggested action(s) open — `career_hunter.py networking`")
    section("INTERVIEWS", b["interviews"],
            lambda a: f"{a.get('job_title')} @ {a.get('company')} — {a.get('interview_date') or 'date UNKNOWN'}",
            "No interviews scheduled.")
    sh = b["source_health"]
    lines.extend(["", "## SOURCE HEALTH",
                  f"- {sh['sources']} sources: " + (", ".join(f"{k} {v}" for k, v in sorted(sh["by_state"].items())) or "none recorded")])
    lines.extend([f"- {f['source']}: {f['health_state']} ({f['error_type'] or ''})" for f in sh["failing"][:8]])
    section("SKILLS GAPS", b["skills_gaps"],
            lambda s: f"{s['skill']} ({s['status'].lower()}) — in {s['jobs']} active job(s)", "No skill gaps in active jobs.")
    section("MARKET SIGNALS", b["market_signals"], str, "No signals.")
    lines.extend(["", "_Nothing in this brief was sent, applied for, or contacted. All actions are yours._"])
    return "\n".join(lines)


def weekly_market_report(today=None, views=None):
    from scripts.intelligence import insights
    today = today or _dt.date.today()
    m = insights.market_intelligence(views, today=today)
    m["week"] = "%d-W%02d" % today.isocalendar()[:2]
    return m


def render_market_report(m):
    def table(title, pairs):
        out = ["", f"## {title}", "", "| | Jobs |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in pairs] or ["| — | 0 |"]
        return out
    lines = [f"# Weekly Market Report — {m['week']}", "", f"{m['total_jobs']} jobs tracked, {m['active_jobs']} active. "
             f"Remote share of active jobs: {m['remote_share'] if m['remote_share'] is not None else 'UNKNOWN'}%.", "",
             "## Signals", *[f"- {s}" for s in m["signals"]]]
    lines += table("By country", m["by_country"]) + table("By role", m["by_role"]) + table("By company", m["by_company"])
    lines += table("By employment type", m["by_employment_type"]) + table("Opportunity score distribution",
                                                                          m["opportunity_distribution"])
    lines += table("Jobs found per week", m["jobs_found_by_week"])
    lines += ["", "## Posted salaries", f"_{m['salary_note']}_"]
    lines += [f"- {k}: n={v['n']}, min {v['min']:g}, median {v['median']:g}, max {v['max']:g}"
              for k, v in m["posted_salaries"].items()] or ["- none posted"]
    lines += ["", "## Top companies"]
    lines += [f"- {c['grade']} {c['company']} — {c['active_opportunities']} active, trend {c['hiring_trend']}"
              for c in m["top_companies"]] or ["- none"]
    return "\n".join(lines)


def weekly_skills_report(today=None, views=None):
    from scripts.intelligence import insights
    today = today or _dt.date.today()
    s = insights.skills_intelligence(views)
    s["week"] = "%d-W%02d" % today.isocalendar()[:2]
    return s


def render_skills_report(s):
    lines = [f"# Weekly Skills Gap Report — {s['week']}", "", f"Based on {s['active_jobs']} active job(s). {s['note']}", "",
             "## Priority learning", "", "| Skill | Status | Required in | Preferred in | Avg opportunity | Would help with |",
             "|---|---|---|---|---|---|"]
    lines += [f"| {r['skill']} | {r['status']} | {r['required_in']} | {r['preferred_in']} | {r['avg_opportunity']} | "
              f"{', '.join(r['unlocks'][:3]) or '—'} |" for r in s["priority_learning"]] or ["| — | | | | | |"]
    lines += ["", "## Most demanded skills you already have"]
    lines += [f"- {r['skill']}: required in {r['required_in']}, preferred in {r['preferred_in']}" for r in s["matched"][:10]] or ["- none"]
    lines += ["", "## Transferable (not yet demonstrated)"]
    lines += [f"- {r['skill']} ({r['jobs']} job(s))" for r in s["transferable"]] or ["- none"]
    return "\n".join(lines)


def write_report(kind, today=None, out_dir=None):
    """kind: daily | weekly_market | weekly_skills. Returns (path, data)."""
    today = today or _dt.date.today()
    out_dir = Path(out_dir) if out_dir else paths.REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "daily":
        data = daily_brief(today)
        text, name, latest = render_daily_brief(data), f"daily_brief_{today.isoformat()}.md", "daily_brief.md"
    elif kind == "weekly_market":
        data = weekly_market_report(today)
        text, name, latest = render_market_report(data), f"weekly_market_{data['week']}.md", "weekly_market.md"
    elif kind == "weekly_skills":
        data = weekly_skills_report(today)
        text, name, latest = render_skills_report(data), f"weekly_skills_{data['week']}.md", "weekly_skills.md"
    else:
        raise ValueError(f"Unknown report {kind!r}")
    (out_dir / name).write_text(text, encoding="utf-8")
    (out_dir / latest).write_text(text, encoding="utf-8")
    return out_dir / name, data
