"""Company careers-page adapter.

Given a company record with a careers_page URL, attempts an HTTP GET. Same
honesty constraint as generic_search.py: no HTML parser is wired up, so a
successful fetch is saved raw for manual/future-parsed review, and the
adapter reports exactly what happened rather than fabricating vacancies.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import storage  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult, http_get_text  # noqa: E402


class CompanyCareersAdapter(SourceAdapter):
    """query: a dict with at least {"company_name": ..., "careers_page": <url>}."""

    name = "company_careers"
    access_type = "PUBLIC_WEB"

    def fetch(self, query=None, limit=None):
        if not query or not query.get("careers_page"):
            return SourceRunResult(source=self.name, status="NOT_IMPLEMENTED",
                                    notes="No careers_page URL provided.")

        company_name = query.get("company_name", "unknown company")
        text, error = http_get_text(query["careers_page"], timeout=10, retries=1)

        if error:
            return SourceRunResult(source=f"careers:{company_name}", status="UNAVAILABLE", error=error)

        storage.save_run_snapshot("raw/html_cache", f"careers_{company_name.lower().replace(' ', '_')}",
                                   {"url": query["careers_page"], "html_length": len(text)})

        return SourceRunResult(
            source=f"careers:{company_name}",
            status="FETCHED_UNPARSED",
            raw_count=len(text),
            notes="Careers page fetched but not parsed — review manually or wire up a parser for this company.",
        )
