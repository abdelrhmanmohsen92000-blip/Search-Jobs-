"""Read-side helpers shared by the CLI, reports, scheduler and dashboard (V1.4+).

One place that answers "give me job X with its analysis and company":

    tracking/jobs.csv            canonical job rows (stable `id`)
    data/analyses/<id>.json      full latest analysis (written by the pipeline)
    company_intel                company index (grades, scores)

Nothing here writes, fetches from the network, or invents a field: a job
without a stored analysis is analyzed on the fly from its stored evidence,
and the result is clearly marked `stored: False`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402

UNKNOWN = "UNKNOWN"


def load_jobs():
    return [r for r in storage.read_csv(paths.JOBS_CSV) if r.get("id")]


def find_job(job_id, jobs=None):
    """Exact id match, else a unique id prefix (handy on the CLI). None if not found
    or ambiguous."""
    jobs = load_jobs() if jobs is None else jobs
    job_id = (job_id or "").strip()
    exact = [j for j in jobs if j.get("id") == job_id]
    if exact:
        return exact[0]
    matches = [j for j in jobs if job_id and (j.get("id") or "").startswith(job_id)]
    return matches[0] if len(matches) == 1 else None


def to_opportunity(row):
    from scripts.career_intelligence import opportunity_from_jobs_row
    return opportunity_from_jobs_row(row)


def analysis_for(row, company_lookup=None, contacts=None):
    """Stored analysis when present, else a fresh (unsaved) one."""
    from scripts.intelligence import analysis_engine
    stored = analysis_engine.load_analysis(row.get("id"))
    if stored:
        stored["stored"] = True
        return stored
    opp = to_opportunity(row)
    explicit = opp["scoring_result"] if opp["scoring_result"].get("sub_scores_explicit") else None
    sub_scores = None
    if explicit and all(explicit.get(k) is not None for k in
                        ("technical", "experience", "software", "project", "location", "eligibility",
                         "career_value", "compensation")):
        sub_scores = {k: explicit[k] for k in ("technical", "experience", "software", "project", "location",
                                               "eligibility", "career_value", "compensation")}
    result = analysis_engine.analyze(opp, company_lookup=company_lookup, contacts=contacts,
                                     explicit_sub_scores=sub_scores)
    result["stored"] = False
    return result


def company_index():
    from scripts.intelligence import company_intel
    return company_intel.build_company_index()


def num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
