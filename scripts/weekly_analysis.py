#!/usr/bin/env python3
"""Weekly intelligence rollup.

Reads tracking/jobs.csv, tracking/applications.csv, and tracking/networking.csv
and produces reports/weekly_report.md with performance stats and recommended
strategy changes. Purely derived from logged data — if a tracker is empty,
the corresponding section says so rather than inventing numbers.
"""
import argparse
import collections
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import paths, storage  # noqa: E402


def _top(counter, n=3):
    return counter.most_common(n)


def analyze():
    jobs = storage.read_csv(paths.JOBS_CSV)
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    networking = storage.read_csv(paths.NETWORKING_CSV)
    companies = storage.read_csv(paths.COMPANIES_CSV)

    stats = {
        "opportunities_found": len(jobs),
        "applications": len(applications),
        "interviews": sum(1 for a in applications if a.get("status") == "interviewing" or a.get("interview_stage")),
        "offers": sum(1 for a in applications if a.get("status") == "offer"),
        "rejections": sum(1 for a in applications if a.get("status") == "rejected"),
    }
    stats["rejection_rate"] = round(stats["rejections"] / stats["applications"] * 100, 1) if stats["applications"] else None
    responded = sum(1 for a in applications if a.get("status") not in ("", None))
    stats["response_rate"] = round(responded / stats["applications"] * 100, 1) if stats["applications"] else None

    countries = collections.Counter(j.get("country") for j in jobs if j.get("country"))
    titles = collections.Counter(j.get("job_title") for j in jobs if j.get("job_title"))
    sources = collections.Counter(j.get("source") for j in jobs if j.get("source"))
    app_companies = collections.Counter(a.get("company") for a in applications if a.get("company"))
    networking_channels = collections.Counter(n.get("connection_status") for n in networking if n.get("connection_status"))

    best_companies = sorted(
        (c for c in companies if c.get("ai_fit_score")),
        key=lambda c: float(c.get("ai_fit_score") or 0),
        reverse=True,
    )[:5]

    return {
        "stats": stats,
        "best_markets": _top(countries),
        "best_titles": _top(titles),
        "best_sources": _top(sources),
        "best_companies": best_companies,
        "best_networking_channels": _top(networking_channels),
        "app_companies": _top(app_companies),
    }


def recommend_strategy_changes(analysis):
    recs = []
    stats = analysis["stats"]
    if stats["applications"] == 0:
        recs.append("No applications logged yet — prioritize converting TOP 10 daily opportunities into applications.")
    if stats["rejection_rate"] and stats["rejection_rate"] > 70:
        recs.append("High rejection rate — tighten targeting to score >=70 opportunities only, and review CV match before applying.")
    if not analysis["best_markets"]:
        recs.append("No country data logged — ensure every job record includes a country for market analysis.")
    elif len(analysis["best_markets"]) == 1:
        recs.append(f"Search is concentrated in {analysis['best_markets'][0][0]} — broaden to more regions per docs/search-strategy.md.")
    if not analysis["best_networking_channels"]:
        recs.append("No networking activity logged yet — start building tracking/networking.csv for target companies.")
    if not recs:
        recs.append("Pipeline has enough data for normal operation — keep current strategy, re-check weekly.")
    return recs


def generate_weekly_report(analysis, out_path=None):
    out_path = out_path or (paths.REPORTS_DIR / "weekly_report.md")
    today = _dt.date.today().isoformat()
    s = analysis["stats"]

    lines = [f"# Weekly Intelligence Report — {today}", "", "## Pipeline Stats", ""]
    lines.append(f"- Opportunities found (all-time, tracking/jobs.csv): {s['opportunities_found']}")
    lines.append(f"- Applications: {s['applications']}")
    lines.append(f"- Interviews: {s['interviews']}")
    lines.append(f"- Offers: {s['offers']}")
    lines.append(f"- Rejections: {s['rejections']}")
    lines.append(f"- Rejection rate: {s['rejection_rate']}%" if s['rejection_rate'] is not None else "- Rejection rate: n/a")
    lines.append(f"- Response rate: {s['response_rate']}%" if s['response_rate'] is not None else "- Response rate: n/a")
    lines.append("")

    lines += ["## BEST MARKETS", ""]
    lines += [f"- {c}: {n}" for c, n in analysis["best_markets"]] or ["_no data_"]
    lines += ["", "## BEST JOB TITLES", ""]
    lines += [f"- {t}: {n}" for t, n in analysis["best_titles"]] or ["_no data_"]
    lines += ["", "## BEST SOURCES", ""]
    lines += [f"- {src}: {n}" for src, n in analysis["best_sources"]] or ["_no data_"]
    lines += ["", "## BEST COMPANIES", ""]
    lines += [f"- {c.get('company_name')} (fit {c.get('ai_fit_score')})" for c in analysis["best_companies"]] or ["_no data_"]
    lines += ["", "## BEST NETWORKING CHANNELS", ""]
    lines += [f"- {ch}: {n}" for ch, n in analysis["best_networking_channels"]] or ["_no data_"]

    lines += ["", "## RECOMMENDED STRATEGY CHANGES", ""]
    lines += [f"- {r}" for r in recommend_strategy_changes(analysis)]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    analysis = analyze()
    out = generate_weekly_report(analysis)
    print(f"Weekly report written to {out}")


if __name__ == "__main__":
    main()
