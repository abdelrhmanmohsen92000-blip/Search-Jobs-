"""Web Intelligence Layer — shared types.

Standard search result shape (never invents a missing field — absent data
is None, not a guess):
    {title, url, snippet, source, query, region, timestamp}
"""
import dataclasses
import datetime as _dt
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class SearchResult:
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None
    query: Optional[str] = None
    region: Optional[str] = None
    timestamp: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SearchResult":
        return cls(
            title=d.get("title"), url=d.get("url"), snippet=d.get("snippet"),
            source=d.get("source"), query=d.get("query"), region=d.get("region"),
            timestamp=d.get("timestamp") or _dt.datetime.now().isoformat(timespec="seconds"),
        )

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class SearchProviderResult:
    """What a WebSearchProvider.search() call returns."""
    provider: str
    status: str  # LIVE / UNAVAILABLE / SEARCH_PROVIDER_UNAVAILABLE / ERROR
    results: List[SearchResult] = dataclasses.field(default_factory=list)
    error: Optional[str] = None
    query: Optional[str] = None

    def to_dict(self):
        d = dataclasses.asdict(self)
        d["results"] = [r if isinstance(r, dict) else dataclasses.asdict(r) for r in self.results]
        return d


class WebSearchProvider:
    """Generic interface. Concrete providers: a browser/search session, a
    search API, an external search service, or manual_search_import.py (a
    human/browser-collected batch). The pipeline only depends on this
    interface, never on a specific provider.
    """
    name = "base"

    def search(self, query: str, limit: int = 10) -> SearchProviderResult:
        raise NotImplementedError


@dataclasses.dataclass
class PageExtractionResult:
    status: str  # OK / JS_REQUIRED / UNAVAILABLE / PARSE_ERROR
    url: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    headings: List[str] = dataclasses.field(default_factory=list)
    links: List[str] = dataclasses.field(default_factory=list)
    company: Optional[str] = None
    job_title: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    remote: Optional[bool] = None
    salary: Optional[str] = None
    description: Optional[str] = None
    requirements: List[str] = dataclasses.field(default_factory=list)
    skills: List[str] = dataclasses.field(default_factory=list)
    application_url: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return dataclasses.asdict(self)
