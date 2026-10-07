"""Search-engine discovery (Phase 5): search lead -> fetched page -> verified opportunity.

    query -> provider.search() -> URL validation -> fetch job page ->
    schema.org JobPosting extraction -> raw opportunity (with search_query provenance)

A search result on its own is never an opportunity: its snippet is unverified
text. Only a page whose own structured data describes a JobPosting becomes
one; every other lead is counted (`unverified_leads`) and left for the browser
queue. A provider answering AUTH_REQUIRED / BLOCKED / RATE_LIMITED stops the
run immediately rather than burning the rest of the query budget.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import dedup as dedup_lib  # noqa: E402
from scripts.sources.base import http_fetch  # noqa: E402
from scripts.web import jobposting_parser  # noqa: E402

STOP_STATUSES = ("AUTH_REQUIRED", "BLOCKED", "RATE_LIMITED", "SEARCH_PROVIDER_UNAVAILABLE")
_SKIP_HOSTS = ("linkedin.com", "glassdoor.com", "upwork.com")  # protected: browser queue only


def run_search_discovery(provider, queries, max_results_per_query=10, max_page_fetches=30, fetcher=None):
    """Returns {"status", "opportunities", "provider_results", "stats"}.
    status is the provider's final state: LIVE / EMPTY / AUTH_REQUIRED / BLOCKED / ..."""
    fetch = fetcher or http_fetch
    opportunities, provider_results, seen_urls = [], [], set()
    stats = {"queries_executed": 0, "search_results": 0, "pages_fetched": 0, "page_fetch_errors": 0,
             "verified_job_pages": 0, "unverified_leads": 0, "protected_skipped": 0}
    status = "EMPTY"

    for q in queries:
        query = q["query_string"] if isinstance(q, dict) else q
        result = provider.search(query, limit=max_results_per_query)
        provider_results.append(result)
        stats["queries_executed"] += 1
        if result.status in STOP_STATUSES or result.status in ("PARSER_FAILED", "UNAVAILABLE"):
            status = result.status
            if result.status in STOP_STATUSES:
                break
            continue
        if result.status == "LIVE":
            status = "LIVE"
        for sr in result.results:
            stats["search_results"] += 1
            key = dedup_lib.canonical_url(sr.url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            if any(h in (sr.url or "").lower() for h in _SKIP_HOSTS):
                stats["protected_skipped"] += 1
                continue
            if stats["pages_fetched"] >= max_page_fetches:
                stats["unverified_leads"] += 1
                continue
            body, error, _ = fetch(sr.url, timeout=10, retries=0)
            stats["pages_fetched"] += 1
            if error:
                stats["page_fetch_errors"] += 1
                stats["unverified_leads"] += 1
                continue
            text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else (body or "")
            page = jobposting_parser.parse_job_page(text, sr.url, provider.name)
            if not page.opportunities:
                stats["unverified_leads"] += 1
                continue
            stats["verified_job_pages"] += 1
            for opp in page.opportunities:
                opp["provenance"]["search_query"] = query
                opportunities.append(opp)

    return {"status": status, "opportunities": opportunities, "provider_results": provider_results, "stats": stats}
