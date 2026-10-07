"""Brave Search API provider (Phase 5) — a real WebSearchProvider.

Endpoint: GET https://api.search.brave.com/res/v1/web/search?q=<query>&count=<n>
Auth:     X-Subscription-Token header, read ONLY from the BRAVE_SEARCH_API_KEY
          environment variable (never from a file in this repository).

Honest statuses, never "no jobs" in place of a failure:
    AUTH_REQUIRED   no key configured (no request is made), or HTTP 401
    BLOCKED         HTTP 403 / the network refused the connection
    RATE_LIMITED    HTTP 429
    PARSER_FAILED   a 200 response that is not the documented shape
    UNAVAILABLE     timeout / DNS / 5xx
    EMPTY           the API answered with zero results
    LIVE            results returned

Results are search *leads* (title, URL, snippet). scripts/web/search_discovery.py
turns a lead into an opportunity only after fetching and parsing its page.
"""
import datetime as _dt
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.sources.base import http_fetch  # noqa: E402
from scripts.web.base import SearchProviderResult, SearchResult, WebSearchProvider  # noqa: E402
from scripts.web.jobposting_parser import strip_html  # noqa: E402

API_URL = "https://api.search.brave.com/res/v1/web/search"
CREDENTIAL_ENV = "BRAVE_SEARCH_API_KEY"
MAX_COUNT = 20  # documented per-request maximum


def classify_failure(error, http_status):
    text = (error or "").lower()
    if http_status == 401:
        return "AUTH_REQUIRED"
    if http_status == 429 or "429" in text:
        return "RATE_LIMITED"
    if http_status == 403 or "403" in text or "forbidden" in text:
        return "BLOCKED"
    return "UNAVAILABLE"


class BraveSearchProvider(WebSearchProvider):
    name = "Brave Search API"

    def __init__(self, api_key=None, fetcher=None):
        self.api_key = api_key if api_key is not None else os.environ.get(CREDENTIAL_ENV)
        self._fetch = fetcher or http_fetch
        self.requests_made = 0

    @property
    def configured(self):
        return bool(self.api_key)

    def search(self, query, limit=10):
        if not self.configured:
            return SearchProviderResult(provider=self.name, status="AUTH_REQUIRED", query=query,
                                        error=f"{CREDENTIAL_ENV} is not set — no request was made.")
        count = max(1, min(int(limit or 10), MAX_COUNT))
        url = f"{API_URL}?{urllib.parse.urlencode({'q': query, 'count': count})}"
        body, error, http_status = self._fetch(url, timeout=10, retries=1, headers={
            "Accept": "application/json", "X-Subscription-Token": self.api_key})
        self.requests_made += 1
        if error:
            return SearchProviderResult(provider=self.name, status=classify_failure(error, http_status),
                                        query=query, error=error)
        try:
            data = json.loads(body)
            raw_results = data.get("web", {}).get("results", []) if isinstance(data, dict) else None
            if not isinstance(raw_results, list):
                raise ValueError("missing web.results list")
        except (ValueError, AttributeError) as e:
            return SearchProviderResult(provider=self.name, status="PARSER_FAILED", query=query,
                                        error=f"PARSER_ERROR: {e}")

        now = _dt.datetime.now().isoformat(timespec="seconds")
        results = []
        for item in raw_results[:count]:
            link = item.get("url") if isinstance(item, dict) else None
            if not link or urllib.parse.urlparse(link).scheme not in ("http", "https"):
                continue
            results.append(SearchResult(title=strip_html(item.get("title")), url=link,
                                        snippet=strip_html(item.get("description")), source=self.name,
                                        query=query, timestamp=now))
        return SearchProviderResult(provider=self.name, status="LIVE" if results else "EMPTY",
                                    results=results, query=query)
