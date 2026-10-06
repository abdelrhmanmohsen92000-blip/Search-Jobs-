"""Remotive public API adapter.

API: https://remotive.com/api/remote-jobs?search=<term> (documented, no key
required). We query once per relevant job family keyword (not every single
title, to keep request volume sane) and merge+dedupe results client-side;
final deduplication still happens centrally in scripts/lib/dedup.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult, http_get_json  # noqa: E402

API_URL = "https://remotive.com/api/remote-jobs"
DEFAULT_SEARCH_TERMS = ["BIM", "Revit", "Architect", "Interior Designer", "Architectural"]


def _to_raw_opportunity(job):
    candidate_country = job.get("candidate_required_location")
    return {
        "source": "Remotive",
        "source_url": job.get("url"),
        "job_title": job.get("title", ""),
        "company": job.get("company_name", ""),
        "country": candidate_country if candidate_country and candidate_country.lower() != "worldwide" else None,
        "city": None,
        "remote": True,
        "employment_type": job.get("job_type") or "Remote",
        "date_posted": job.get("publication_date"),
        "skills_required": job.get("tags") or [],
        "description": (job.get("description") or "")[:2000] or None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": job.get("salary") or None,
    }


class RemotiveAdapter(SourceAdapter):
    name = "Remotive"
    access_type = "API"

    def fetch(self, query=None, limit=None, search_terms=None):
        search_terms = search_terms or DEFAULT_SEARCH_TERMS
        max_requests = cfg_lib.search_limits()["max_requests_per_source"]
        search_terms = search_terms[:max_requests]  # Phase 3 safety limit: cap HTTP calls per run, not just results
        all_jobs = {}
        last_error = None
        any_success = False

        for term in search_terms:
            data, error = http_get_json(f"{API_URL}?search={urllib_quote(term)}", timeout=10, retries=2)
            if error:
                last_error = error
                continue
            any_success = True
            for job in (data or {}).get("jobs", []):
                job_id = job.get("id")
                if job_id is not None:
                    all_jobs[job_id] = job

        if not any_success:
            return SourceRunResult(source=self.name, status="UNAVAILABLE", error=last_error)

        jobs = list(all_jobs.values())
        if limit:
            jobs = jobs[:limit]

        if not jobs:
            return SourceRunResult(source=self.name, status="EMPTY")

        opportunities = [_to_raw_opportunity(j) for j in jobs]
        return SourceRunResult(source=self.name, status="SUCCESS", opportunities=opportunities, raw_count=len(jobs))


def urllib_quote(s):
    import urllib.parse

    return urllib.parse.quote(s)
