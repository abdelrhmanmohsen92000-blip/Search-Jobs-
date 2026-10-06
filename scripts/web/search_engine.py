"""Web search orchestration.

Ties the query plan (scripts/search_config.py) to a WebSearchProvider. No
live search API or browser-automation provider is wired up in V1.3 — by
design, since this sandboxed environment cannot drive a browser or call a
paid search API. `run_web_search()` always tells the truth about that:
SEARCH_PROVIDER_UNAVAILABLE when no provider is given, never a pretended
search.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.web.base import SearchProviderResult  # noqa: E402
from scripts.web.manual_search_import import ManualSearchImportProvider  # noqa: E402


def default_provider():
    """The only provider wired up today: manual/browser-collected results
    from data/raw/search_results/. A future PR can add a real search-API or
    browser-session provider here without changing callers — they only
    depend on the WebSearchProvider interface.
    """
    return ManualSearchImportProvider()


def run_web_search(queries, provider=None, limit_per_query=None):
    """queries: list of query strings (or query dicts with a 'query_string').
    provider: a WebSearchProvider, or None to report SEARCH_PROVIDER_UNAVAILABLE.

    Returns a list of SearchProviderResult, one per query attempted (or a
    single SEARCH_PROVIDER_UNAVAILABLE result if no provider is configured).
    """
    if provider is None:
        return [SearchProviderResult(provider="none", status="SEARCH_PROVIDER_UNAVAILABLE",
                                      error="No search provider configured — no live web-search API or "
                                            "browser-automation session is available in this environment. "
                                            "Use manual search import (data/raw/search_results/) or the "
                                            "browser queue (scripts/web/browser_queue.py) instead.")]

    results = []
    query_strings = [q["query_string"] if isinstance(q, dict) else q for q in queries] or [None]
    for q in query_strings:
        results.append(provider.search(q, limit=limit_per_query))
    return results
