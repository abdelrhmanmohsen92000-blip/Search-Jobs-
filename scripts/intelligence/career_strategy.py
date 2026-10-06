"""Career strategy engine (V1.4).

Analyzes logged opportunities/applications over time to identify the
best-performing countries, titles, companies, platforms, work modes, and
employment types — and the weak spots (low-performing sources, repeated
rejections, skill gaps, application bottlenecks). Builds on
scripts/weekly_analysis.py's existing aggregation rather than duplicating it.

Also hosts market_intelligence(): aggregated demand signals from
tracking/jobs.csv, always reported with a sample size — never a bare claim.
"""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, staleness, storage  # noqa: E402
from scripts import weekly_analysis  # noqa: E402

MIN_SAMPLE_SIZE = 3


def best_of(pairs, n=5):
    return sorted(pairs, key=lambda kv: kv[1], reverse=True)[:n]


def career_strategy_report():
    """Returns the V1.1-preserved weekly analysis plus work-mode/employment-type
    breakdowns and application bottleneck detection, all derived from logged
    data only.
    """
    jobs = storage.read_csv(paths.JOBS_CSV)
    applications = storage.read_csv(paths.APPLICATIONS_CSV)
    analysis = weekly_analysis.analyze()

    work_modes = collections.Counter(j.get("employment_type") for j in jobs if j.get("employment_type"))
    remote_count = sum(1 for j in jobs if (j.get("remote") or "").strip().lower() in ("true", "1"))

    weak_sources = {
        src: stats for src, stats in collections.Counter(j.get("source") for j in jobs if j.get("source")).items()
        if stats < MIN_SAMPLE_SIZE
    }

    pending_statuses = {"NEW", "REVIEW", "READY_TO_APPLY"}
    bottleneck = [a for a in applications if (a.get("status") or "").strip().upper() in pending_statuses]

    return {
        "best_countries": analysis["best_markets"],
        "best_titles": analysis["best_titles"],
        "best_companies": analysis["best_companies"],
        "best_sources": analysis["best_sources"],
        "best_work_modes": best_of(list(work_modes.items())),
        "remote_opportunity_count": remote_count,
        "weak_sources": weak_sources,
        "skill_gaps": analysis["skill_gaps"],
        "application_bottleneck": bottleneck,
        "recommended_changes": weekly_analysis.recommend_strategy_changes(analysis),
    }


def market_intelligence(jobs=None, min_sample_size=MIN_SAMPLE_SIZE):
    """Aggregated demand signals from tracking/jobs.csv. Every figure carries
    its own sample_size; a dimension with too few records is marked
    insufficient rather than asserted as a trend.
    """
    jobs = jobs if jobs is not None else storage.read_csv(paths.JOBS_CSV)
    n = len(jobs)

    skills = collections.Counter()
    for j in jobs:
        for col in ("skills_required", "software_required"):
            for item in (j.get(col) or "").split(";"):
                if item.strip():
                    skills[item.strip()] += 1

    titles = collections.Counter(j.get("job_title") for j in jobs if j.get("job_title"))
    countries = collections.Counter(j.get("country") for j in jobs if j.get("country"))
    remote_count = sum(1 for j in jobs if (j.get("remote") or "").strip().lower() in ("true", "1"))
    freelance_count = sum(1 for j in jobs if (j.get("employment_type") or "").strip().lower() in ("freelance", "project-based"))

    salaries = [j for j in jobs if j.get("salary_min") or j.get("salary_max")]
    observed = [j for j in salaries if (j.get("salary_confidence") or "").upper() == "OBSERVED"]
    estimated = [j for j in salaries if (j.get("salary_confidence") or "").upper() == "ESTIMATED"]

    if len(observed) >= min_sample_size:
        salary_pattern = f"{len(observed)} OBSERVED salary record(s) logged — see salary_min/salary_max in tracking/jobs.csv."
    elif salaries:
        salary_pattern = (f"Only {len(salaries)} salary record(s) logged ({len(observed)} observed, "
                           f"{len(estimated)} estimated) — below the sample size needed to call this a pattern.")
    else:
        salary_pattern = "DATA_INSUFFICIENT"

    return {
        "sample_size": n,
        "confidence": "LOW" if n < min_sample_size else ("MEDIUM" if n < 20 else "HIGH"),
        "most_requested_skills": skills.most_common(10),
        "most_common_job_titles": titles.most_common(10),
        "strongest_demand_countries": countries.most_common(10),
        "remote_demand": {"count": remote_count, "share": round(remote_count / n * 100, 1) if n else None},
        "freelance_demand": {"count": freelance_count, "share": round(freelance_count / n * 100, 1) if n else None},
        "salary_data_available": len(salaries),
        "salary_observed_count": len(observed),
        "salary_estimated_count": len(estimated),
        "salary_pattern": salary_pattern,
    }
