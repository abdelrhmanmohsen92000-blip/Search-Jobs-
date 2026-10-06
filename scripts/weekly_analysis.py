#!/usr/bin/env python3
"""Weekly intelligence rollup.

Reads tracking/jobs.csv, tracking/applications.csv, tracking/companies.csv,
and tracking/networking.csv and produces:
    reports/weekly_report.md    - pipeline stats + top markets/titles/sources/companies
    reports/weekly_strategy.md  - the 10 strategy questions (Phase 14), answered
                                   from logged data, with concrete next-week changes

Purely derived from logged data — if a tracker is empty, the corresponding
section says so rather than inventing numbers.
"""
import argparse
import collections
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import paths, storage  # noqa: E402

APPLIED_STATUSES = {"APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "ACCEPTED", "REJECTED", "CLOSED"}
RESPONSE_STATUSES = {"FOLLOW_UP", "INTERVIEW", "OFFER", "ACCEPTED", "REJECTED"}


def _top(counter, n=5):
    return counter.most_common(n)


def _status(a):
    return (a.get("status") or "").strip().upper()


def analyze():
    jobs = storage.read_csv(paths.JOBS_CSV)
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    networking = storage.read_csv(paths.NETWORKING_CSV)
    companies = storage.read_csv(paths.COMPANIES_CSV)

    applied = [a for a in applications if _status(a) in APPLIED_STATUSES]
    stats = {
        "opportunities_found": len(jobs),
        "applications": len(applied),
        "interviews": sum(1 for a in applications if _status(a) == "INTERVIEW"),
        "offers": sum(1 for a in applications if _status(a) in ("OFFER", "ACCEPTED")),
        "rejections": sum(1 for a in applications if _status(a) == "REJECTED"),
    }
    stats["rejection_rate"] = round(stats["rejections"] / len(applied) * 100, 1) if applied else None
    responded = sum(1 for a in applied if _status(a) in RESPONSE_STATUSES)
    stats["response_rate"] = round(responded / len(applied) * 100, 1) if applied else None

    countries = collections.Counter(j.get("country") for j in jobs if j.get("country"))
    titles_scores = collections.defaultdict(list)
    for j in jobs:
        if j.get("job_title") and j.get("score"):
            try:
                titles_scores[j["job_title"]].append(float(j["score"]))
            except ValueError:
                continue
    best_titles_by_score = sorted(titles_scores.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), reverse=True)[:5]
    titles = collections.Counter(j.get("job_title") for j in jobs if j.get("job_title"))
    sources = collections.Counter(j.get("source") for j in jobs if j.get("source"))
    app_companies = collections.Counter(a.get("company") for a in applications if a.get("company"))
    repeat_companies = [(c, n) for c, n in collections.Counter(j.get("company") for j in jobs if j.get("company")).items() if n > 1]
    networking_channels = collections.Counter(n.get("connection_status") for n in networking if n.get("connection_status"))
    skill_gaps = collections.Counter()
    for j in jobs:
        for s in (j.get("skills_required") or "").split(";"):
            if s.strip():
                skill_gaps[s.strip()] += 1

    best_companies = sorted(
        (c for c in companies if c.get("ai_fit_score")),
        key=lambda c: float(c.get("ai_fit_score") or 0),
        reverse=True,
    )[:5]

    responding_networking = [n for n in networking if n.get("message_status") not in ("", "not_drafted", None)]

    return {
        "stats": stats,
        "best_markets": _top(countries),
        "best_titles": _top(titles),
        "best_titles_by_score": best_titles_by_score,
        "best_sources": _top(sources),
        "best_companies": best_companies,
        "repeat_companies": sorted(repeat_companies, key=lambda kv: kv[1], reverse=True)[:5],
        "best_networking_channels": _top(networking_channels),
        "app_companies": _top(app_companies),
        "skill_gaps": skill_gaps.most_common(5),
        "responding_networking_count": len(responding_networking),
    }


def recommend_strategy_changes(analysis):
    recs = []
    stats = analysis["stats"]
    if stats["applications"] == 0:
        recs.append("No applications logged yet — prioritize converting TOP opportunities (score >= 70) into applications.")
    if stats["rejection_rate"] and stats["rejection_rate"] > 70:
        recs.append("High rejection rate — tighten targeting to score >=70 opportunities only, and review CV match before applying.")
    if not analysis["best_markets"]:
        recs.append("No country data logged — ensure every job record includes a country for market analysis.")
    elif len(analysis["best_markets"]) == 1:
        recs.append(f"Search is concentrated in {analysis['best_markets'][0][0]} — broaden to more regions per docs/search-strategy.md.")
    if not analysis["best_networking_channels"]:
        recs.append("No networking activity logged yet — start building tracking/networking.csv for target companies.")
    if analysis["skill_gaps"]:
        top_gap = analysis["skill_gaps"][0][0]
        recs.append(f"'{top_gap}' is the most frequently requested skill not yet matched — consider a focused upskill or portfolio piece.")
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


def generate_weekly_strategy(analysis, out_path=None):
    """Answers the 10 Phase 14 strategy questions directly from logged data."""
    out_path = out_path or (paths.REPORTS_DIR / "weekly_strategy.md")
    today = _dt.date.today().isoformat()

    def fmt_pairs(pairs, empty="Not enough data yet."):
        return "\n".join(f"- {a}: {b}" for a, b in pairs) if pairs else empty

    lines = [f"# Weekly Strategy — {today}", ""]

    lines += ["## 1. Which countries are strongest?", "", fmt_pairs(analysis["best_markets"]), ""]
    lines += ["## 2. Which job titles produce the highest match?", "",
              fmt_pairs([(t, round(sum(scores) / len(scores), 1)) for t, scores in
                         [(t, s) for t, s in analysis["best_titles_by_score"]]], "Not enough scored data yet."), ""]
    lines += ["## 3. Which companies repeatedly appear?", "", fmt_pairs(analysis["repeat_companies"]), ""]
    lines += ["## 4. Which platforms produce the best opportunities?", "", fmt_pairs(analysis["best_sources"]), ""]
    lines += ["## 5. Which applications get responses?", "",
              f"{analysis['stats']['response_rate']}% response rate across logged applications."
              if analysis['stats']['response_rate'] is not None else "No applications logged yet.", ""]
    lines += ["## 6. Which applications get rejected?", "",
              f"{analysis['stats']['rejection_rate']}% rejection rate across logged applications."
              if analysis['stats']['rejection_rate'] is not None else "No applications logged yet.", ""]
    lines += ["## 7. Which networking actions work?", "",
              f"{analysis['responding_networking_count']} contact(s) with a message sent/in progress "
              f"(see tracking/networking.csv `message_status`).", ""]
    lines += ["## 8. Which skills are repeatedly requested?", "", fmt_pairs(analysis["skill_gaps"]), ""]
    lines += ["## 9. Which CV version performs best?", "",
              "Not tracked yet — log `cv_version` per row in tracking/applications.csv and re-run this report "
              "once enough applications have outcomes to compare.", ""]
    lines += ["## 10. What should the candidate change next week?", ""]
    lines += [f"- {r}" for r in recommend_strategy_changes(analysis)]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    analysis = analyze()
    out = generate_weekly_report(analysis)
    strategy_out = generate_weekly_strategy(analysis)
    print(f"Weekly report written to {out}")
    print(f"Weekly strategy written to {strategy_out}")


if __name__ == "__main__":
    main()
