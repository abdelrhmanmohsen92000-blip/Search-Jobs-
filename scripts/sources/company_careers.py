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

import yaml  # noqa: E402

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402
from scripts.lib import source_health as source_health_lib  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult, http_fetch  # noqa: E402
from scripts.web import jobposting_parser  # noqa: E402

COMPANY_SOURCES_FIELDNAMES = [
    "company", "career_url", "source_type", "region", "priority", "enabled", "last_checked", "last_status",
]
TARGET_COMPANIES = paths.CONFIG_DIR / "target_companies.yaml"


def _decode(body):
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else (body or "")


class CompanyCareersAdapter(SourceAdapter):
    """query: {"company_name", "careers_page", optional "max_requests"}.

    Fetches the careers page, extracts schema.org JobPosting data from it,
    then follows same-site job-detail links (bounded by max_requests) and
    extracts from those. Status is SUCCESS only when real postings were
    parsed; FETCHED_UNPARSED when pages were reached but carried no
    structured job data (no opportunity is invented from page text);
    PARSE_ERROR when the structured data itself was unreadable.
    """

    name = "company_careers"
    access_type = "PUBLIC_WEB"

    def fetch(self, query=None, limit=None):
        if not query or not query.get("careers_page"):
            return SourceRunResult(source=self.name, status="NOT_IMPLEMENTED",
                                    notes="No careers_page URL provided.")

        company_name = query.get("company_name", "unknown company")
        source = f"careers:{company_name}"
        careers_page = query["careers_page"]
        max_requests = max(1, int(query.get("max_requests") or cfg_lib.search_limits()["max_requests_per_source"]))

        body, error, http_status = http_fetch(careers_page, timeout=10, retries=1)
        if error:
            return SourceRunResult(source=source, status="UNAVAILABLE", error=error, http_status=http_status,
                                   requests_made=1)

        html_text = _decode(body)
        pages = [jobposting_parser.parse_job_page(html_text, careers_page, source, company_name)]
        requests_made, link_errors = 1, 0
        for link in jobposting_parser.extract_job_links(html_text, careers_page, limit=max_requests - 1):
            link_body, link_error, _ = http_fetch(link, timeout=10, retries=0)
            requests_made += 1
            if link_error:
                link_errors += 1
                continue
            pages.append(jobposting_parser.parse_job_page(_decode(link_body), link, source, company_name))

        opportunities = []
        for page in pages:
            for opp in page.opportunities:
                opp["company_career_url"] = careers_page
                opportunities.append(opp)
        if limit:
            opportunities = opportunities[:limit]

        notes = (f"{requests_made} request(s), {len(pages)} page(s) parsed, "
                 f"{link_errors} job link(s) unreachable")
        if opportunities:
            return SourceRunResult(source=source, status="SUCCESS", opportunities=opportunities,
                                   raw_count=len(opportunities), http_status=http_status,
                                   requests_made=requests_made, notes=notes)
        if any(p.status == "PARSER_FAILED" for p in pages):
            return SourceRunResult(source=source, status="PARSE_ERROR", http_status=http_status,
                                   error="PARSER_ERROR: JSON-LD present but unreadable",
                                   requests_made=requests_made, notes=notes)
        return SourceRunResult(
            source=source, status="FETCHED_UNPARSED", raw_count=len(html_text), http_status=http_status,
            requests_made=requests_made,
            notes=notes + " — no schema.org JobPosting data found; review manually (browser queue).",
        )


def load_targets(path=None):
    """Entries from config/target_companies.yaml (empty list if absent)."""
    path = path or TARGET_COMPANIES
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("companies") or []


def has_verified_url(target):
    url = (target.get("career_url") or "").strip()
    status = (target.get("url_verification") or {}).get("status")
    return url.startswith(("http://", "https://")) and status in ("SEARCH_INDEXED", "LIVE_VERIFIED")


def target_rows(targets):
    """Registry entries as career-page rows. An entry without a verified URL
    is never turned into a fetchable row (it goes to the browser queue)."""
    rows = []
    for t in targets:
        if not has_verified_url(t):
            continue
        rows.append({
            "company": t.get("company"), "career_url": t["career_url"], "source_type": t.get("source_type", ""),
            "region": (t.get("regions") or ["UNKNOWN"])[0], "priority": t.get("priority", "MEDIUM"),
            "enabled": bool(t.get("enabled", True)), "last_checked": "", "last_status": "",
        })
    return rows


def unverified_targets(targets):
    return [t for t in targets if not has_verified_url(t)]


def load_company_sources(csv_path=None):
    return storage.read_csv(csv_path or paths.COMPANY_CAREER_PAGES_CSV)


def add_company_source(company, career_url, source_type="", region="UNKNOWN", priority="MEDIUM", enabled=True, csv_path=None):
    """Adds one row. Never called with a fabricated URL by this codebase —
    the caller (a human, via the CLI) is asserting they've verified it.

    priority (Phase 4 §COMPANY STRATEGY): a starting HIGH/MEDIUM/LOW hint the
    caller supplies (e.g. from portfolio/geography/role relevance); this
    module never computes or upgrades it on its own — that would be
    inventing a company-fit judgment the codebase has no evidence for.
    region defaults to UNKNOWN rather than guessed from the URL/company name.
    """
    csv_path = csv_path or paths.COMPANY_CAREER_PAGES_CSV
    row = {
        "company": company, "career_url": career_url, "source_type": source_type,
        "region": region, "priority": priority,
        "enabled": enabled, "last_checked": "", "last_status": "",
    }
    storage.append_csv_rows(csv_path, COMPANY_SOURCES_FIELDNAMES, [row])
    return row


def _is_enabled(row):
    return str(row.get("enabled", "")).strip().lower() in ("true", "1", "yes")


def plan_company_sources(csv_path=None, limit=None, targets=None, health=None, now=None):
    """Which career pages a run would check, in priority order, without
    fetching or writing anything (used by --dry-run as well as by the run).

    Returns (all_rows, to_check, cooled_down): all_rows is the CSV state
    plus any registry target not yet in it; to_check are enabled rows with a
    URL, HIGH priority first, capped at `limit`; cooled_down are rows skipped
    because that company's page is inside a source-health backoff window.
    """
    rows = load_company_sources(csv_path or paths.COMPANY_CAREER_PAGES_CSV)
    known = {(r.get("company") or "").strip().lower() for r in rows}
    for row in target_rows(targets or []):
        if row["company"].strip().lower() not in known:
            rows.append(row)
    health = health if health is not None else {}
    priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    candidates = [r for r in rows if _is_enabled(r) and r.get("career_url")]
    if limit or targets:
        candidates.sort(key=lambda r: priority_rank.get((r.get("priority") or "MEDIUM").upper(), 1))
    cooled = [r for r in candidates if source_health_lib.in_cooldown(health.get(f"careers:{r.get('company')}"), now)]
    to_check = [r for r in candidates if r not in cooled]
    if limit:
        to_check = to_check[:limit]
    return rows, to_check, cooled


def run_configured_company_sources(csv_path=None, limit=None, targets=None, health=None, max_requests=None):
    """Fetches every enabled career page (tracking/company_career_pages.csv,
    plus config/target_companies.yaml entries when `targets` is given) via
    CompanyCareersAdapter, updates last_checked/last_status in place, and
    returns the list of SourceRunResult (never raises — one bad row/company
    is isolated from the rest, same failure-isolation contract as every
    other source in scripts/sources/). Pages inside a cooldown window are
    reported as COOLDOWN and not requested.
    """
    csv_path = csv_path or paths.COMPANY_CAREER_PAGES_CSV
    rows, to_check, cooled = plan_company_sources(csv_path, limit, targets, health)
    adapter = CompanyCareersAdapter()
    results = []
    now = _dt.datetime.now().isoformat(timespec="seconds")
    checked_ids = {id(r) for r in to_check}

    updated_rows = []
    for row in rows:
        if id(row) not in checked_ids:
            updated_rows.append(row)
            continue
        query = {"company_name": row.get("company"), "careers_page": row.get("career_url")}
        if max_requests:
            query["max_requests"] = max_requests
        try:
            result = adapter.fetch(query)
        except Exception as e:  # noqa: BLE001 - one company's failure must never break the others
            result = SourceRunResult(source=f"careers:{row.get('company')}", status="ERROR",
                                      error=f"{type(e).__name__}: {e}")
        results.append(result)
        updated_rows.append({**row, "last_checked": now, "last_status": result.status})

    for row in cooled:
        results.append(SourceRunResult(source=f"careers:{row.get('company')}", status="COOLDOWN",
                                       notes="Skipped: inside source-health backoff window."))

    if updated_rows:
        storage.write_csv(csv_path, COMPANY_SOURCES_FIELDNAMES, updated_rows)
    return results
