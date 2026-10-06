"""Manual search-result import.

Reads data/raw/search_results/*.json — each file a JSON list of search
result dicts (title/url/snippet/source/query/region/timestamp), as a human
would export/copy from a real browser search session. This is the primary
way real web-search results enter the system today; see README "Manual
search import".
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths  # noqa: E402
from scripts.web.base import SearchProviderResult, SearchResult, WebSearchProvider  # noqa: E402

SEARCH_RESULTS_DIR = paths.DATA_RAW / "search_results"


def load_single_file(file_path):
    """Load one search-results JSON file. Returns (results, errors)."""
    file_path = Path(file_path)
    results, errors = [], []
    if not file_path.exists():
        errors.append(f"{file_path}: file not found")
        return results, errors
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"{file_path.name}: {e}")
        return results, errors
    batch = data if isinstance(data, list) else [data]
    for item in batch:
        if not isinstance(item, dict):
            errors.append(f"{file_path.name}: non-object entry skipped")
            continue
        results.append(SearchResult.from_dict(item))
    return results, errors


def load_search_result_files(directory=None):
    """Returns (results, files_read, errors). Never fabricates a result for
    a file it can't parse — such files are reported in `errors`, not skipped
    silently.
    """
    directory = directory or SEARCH_RESULTS_DIR
    results, files_read, errors = [], [], []

    if not directory.exists():
        return results, files_read, errors

    for f in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{f.name}: {e}")
            continue
        batch = data if isinstance(data, list) else [data]
        for item in batch:
            if not isinstance(item, dict):
                errors.append(f"{f.name}: non-object entry skipped")
                continue
            results.append(SearchResult.from_dict(item))
        files_read.append(f.name)

    return results, files_read, errors


class ManualSearchImportProvider(WebSearchProvider):
    """A WebSearchProvider backed by human/browser-collected files rather
    than a live query — `search()` ignores `query`/`limit` and simply
    returns whatever has been imported, so it fits the same interface every
    other provider does.
    """
    name = "Manual Search Import"

    def __init__(self, directory=None):
        self.directory = directory or SEARCH_RESULTS_DIR

    def search(self, query=None, limit=None):
        results, files_read, errors = load_search_result_files(self.directory)
        if limit:
            results = results[:limit]
        if errors and not results:
            return SearchProviderResult(provider=self.name, status="ERROR", error="; ".join(errors), query=query)
        if not results:
            return SearchProviderResult(provider=self.name, status="UNAVAILABLE",
                                         error="No files in data/raw/search_results/", query=query)
        return SearchProviderResult(provider=self.name, status="LIVE", results=results, query=query)
