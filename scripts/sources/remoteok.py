"""Remote OK public JSON feed adapter.

API: https://remoteok.com/api (no key required). Returns a JSON array whose
first element is a legend/metadata object (no `id` field) — real listings
follow. This adapter filters to roles relevant to the candidate's job title
matrix and normalizes each into a raw opportunity dict compatible with
schemas/opportunity.schema.json (full normalization still happens centrally
in scripts/lib/normalize.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult, http_get_json  # noqa: E402

API_URL = "https://remoteok.com/api"


def _relevant(job, titles_lower):
    position = (job.get("position") or "").lower()
    tags = " ".join(job.get("tags") or []).lower()
    return any(t in position or t in tags for t in titles_lower)


def _to_raw_opportunity(job):
    return {
        "source": "Remote OK",
        "source_url": job.get("url") or f"https://remoteok.com/remote-jobs/{job.get('id', '')}",
        "job_title": job.get("position", ""),
        "company": job.get("company", ""),
        "country": None,
        "city": None,
        "remote": True,
        "employment_type": "Remote",
        "date_posted": job.get("date"),
        "skills_required": job.get("tags") or [],
        "description": (job.get("description") or "")[:2000] or None,
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "salary_currency": "USD" if (job.get("salary_min") or job.get("salary_max")) else None,
    }


class RemoteOKAdapter(SourceAdapter):
    name = "Remote OK"
    access_type = "API"

    def fetch(self, query=None, limit=None):
        titles_lower = [t.lower() for t in cfg_lib.all_job_titles()]
        data, error = http_get_json(API_URL, timeout=10, retries=2)

        if error:
            return SourceRunResult(source=self.name, status="UNAVAILABLE", error=error)

        if not isinstance(data, list):
            return SourceRunResult(source=self.name, status="ERROR", error="Unexpected response shape (expected a list)")

        jobs = [j for j in data if isinstance(j, dict) and j.get("id")]  # drop the legend row
        relevant = [j for j in jobs if _relevant(j, titles_lower)]
        if limit:
            relevant = relevant[:limit]

        if not relevant:
            return SourceRunResult(source=self.name, status="EMPTY", raw_count=len(jobs))

        opportunities = [_to_raw_opportunity(j) for j in relevant]
        return SourceRunResult(source=self.name, status="SUCCESS", opportunities=opportunities, raw_count=len(jobs))
