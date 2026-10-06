"""Generic PUBLIC_WEB search-board adapter.

For boards in config/sources.yaml tagged access_method: PUBLIC_WEB (e.g.
Indeed, Bayt, GulfTalent) there is no documented JSON API, so the only
honest thing an adapter without a browser/HTML-parsing stack can do is:
  1. attempt an HTTP GET of the board's public search URL,
  2. if reachable, save the raw HTML into data/raw/ for a later parsing
     pass (or a browser-capable session) rather than inventing structured
     results from unparsed markup,
  3. if unreachable (network policy, timeout, non-200), report
     SOURCE_STATUS = UNAVAILABLE with the real error.

This NEVER returns fabricated opportunities. It is the integration point a
future HTML parser (or a browser-driving agent) plugs into — see README
"How to add a new source".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths, storage  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult, http_get_text  # noqa: E402


class GenericSearchAdapter(SourceAdapter):
    """query: a dict with at least {"source": <name>, "search_url": <url>}."""

    name = "generic_search"
    access_type = "PUBLIC_WEB"

    def fetch(self, query=None, limit=None):
        if not query or not query.get("search_url"):
            return SourceRunResult(source=self.name, status="NOT_IMPLEMENTED",
                                    notes="No search_url provided for this board.")

        source_name = query.get("source", self.name)
        text, error = http_get_text(query["search_url"], timeout=10, retries=1)

        if error:
            return SourceRunResult(source=source_name, status="UNAVAILABLE", error=error)

        snapshot_name = f"raw_html_{source_name.lower().replace(' ', '_')}"
        storage.save_run_snapshot("raw/html_cache", snapshot_name, {"url": query["search_url"], "html_length": len(text)})

        return SourceRunResult(
            source=source_name,
            status="FETCHED_UNPARSED",
            raw_count=len(text),
            notes="Page fetched but not parsed (no HTML parser wired up yet) — "
                  "0 opportunities extracted. See README 'How to add a new source'.",
        )
