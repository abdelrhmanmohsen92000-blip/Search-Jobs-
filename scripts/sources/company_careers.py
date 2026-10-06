"""Company careers-page adapter.

Given a company record with a careers_page URL, attempts an HTTP GET. Same
honesty constraint as generic_search.py: no HTML parser is wired up, so a
successful fetch is saved raw for manual/future-parsed review, and the
adapter reports exactly what happened rather than fabricating vacancies.

Company career pages are a first-class, configurable source (Phase 3 §11):
tracking/company_career_pages.csv holds {company, career_url, source_type,
enabled, last_checked, last_status} rows. It ships EMPTY — this repository
has no independently verified company career URL to seed it with, and one is
never fabricated. See config/company_career_pages.example.yaml for the
structure and `career_hunter.py company-sources --add` to add a real,
verified one.
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult, http_get_text  # noqa: E402

COMPANY_SOURCES_FIELDNAMES = ["company", "career_url", "source_type", "enabled", "last_checked", "last_status"]


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


def load_company_sources(csv_path=None):
    return storage.read_csv(csv_path or paths.COMPANY_CAREER_PAGES_CSV)


def add_company_source(company, career_url, source_type="", enabled=True, csv_path=None):
    """Adds one row. Never called with a fabricated URL by this codebase —
    the caller (a human, via the CLI) is asserting they've verified it.
    """
    csv_path = csv_path or paths.COMPANY_CAREER_PAGES_CSV
    row = {
        "company": company, "career_url": career_url, "source_type": source_type,
        "enabled": enabled, "last_checked": "", "last_status": "",
    }
    storage.append_csv_rows(csv_path, COMPANY_SOURCES_FIELDNAMES, [row])
    return row


def run_configured_company_sources(csv_path=None, limit=None):
    """Fetches every enabled row in tracking/company_career_pages.csv via
    CompanyCareersAdapter, updates last_checked/last_status in place, and
    returns the list of SourceRunResult (never raises — one bad row/company
    is isolated from the rest, same failure-isolation contract as every
    other source in scripts/sources/).
    """
    csv_path = csv_path or paths.COMPANY_CAREER_PAGES_CSV
    rows = load_company_sources(csv_path)
    adapter = CompanyCareersAdapter()
    results = []
    now = _dt.datetime.now().isoformat(timespec="seconds")

    updated_rows = []
    checked = 0
    for row in rows:
        enabled = str(row.get("enabled", "")).strip().lower() in ("true", "1", "yes")
        if not enabled or not row.get("career_url") or (limit and checked >= limit):
            updated_rows.append(row)
            continue
        try:
            result = adapter.fetch({"company_name": row.get("company"), "careers_page": row.get("career_url")})
        except Exception as e:  # noqa: BLE001 - one company's failure must never break the others
            result = SourceRunResult(source=f"careers:{row.get('company')}", status="ERROR",
                                      error=f"{type(e).__name__}: {e}")
        results.append(result)
        checked += 1
        updated_rows.append({**row, "last_checked": now, "last_status": result.status})

    if updated_rows:
        storage.write_csv(csv_path, COMPANY_SOURCES_FIELDNAMES, updated_rows)
    return results
