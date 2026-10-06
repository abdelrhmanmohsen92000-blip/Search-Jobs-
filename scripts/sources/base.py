"""Source adapter base class + shared HTTP helpers.

Every adapter in scripts/sources/ implements fetch() and returns a
SourceRunResult. The pipeline (scripts/daily_research.py) never talks to a
source directly — it only calls adapters through this interface, so a new
source can be added without touching the scoring engine or the pipeline
orchestration.

Status values (never fabricated — a failed/blocked source reports why):
    SUCCESS          - live data retrieved
    EMPTY            - reached the source, zero results for this query
    BROWSER_REQUIRED - source needs a human-controlled/logged-in browser session
    UNAVAILABLE      - reachable in principle but failed this run (network
                        policy block, timeout, non-200, DNS failure, etc.)
    ERROR            - adapter raised while parsing a response it did get
    NOT_IMPLEMENTED  - adapter exists as an interface/stub only
"""
import dataclasses
import datetime as _dt
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "CareerHunter/1.2 (+https://github.com/; research tool, not a scraper of protected pages)"


@dataclasses.dataclass
class SourceRunResult:
    source: str
    status: str
    opportunities: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    error: Optional[str] = None
    attempted_at: str = dataclasses.field(default_factory=lambda: _dt.datetime.now().isoformat(timespec="seconds"))
    raw_count: int = 0
    notes: Optional[str] = None

    def to_dict(self):
        return dataclasses.asdict(self)


class SourceAdapter:
    name = "base"
    access_type = "UNKNOWN"  # API / PUBLIC_WEB / BROWSER_REQUIRED / MANUAL

    def fetch(self, query=None, limit=None) -> SourceRunResult:
        raise NotImplementedError


def http_get_json(url, timeout=10, retries=2, backoff=1.5, headers=None):
    """GET a URL and parse JSON, with timeout + retry. Returns (data, error).

    Never raises: on final failure returns (None, "<reason>") so callers can
    report SOURCE_STATUS = UNAVAILABLE instead of crashing the pipeline.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    last_error = f"HTTP {resp.status}"
                else:
                    body = resp.read()
                    return json.loads(body), None
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            last_error = f"URLError: {e.reason}"
        except (json.JSONDecodeError, TimeoutError) as e:
            last_error = f"{type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001 - adapters must never crash the pipeline
            last_error = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(backoff ** attempt)
    return None, last_error


def http_get_text(url, timeout=10, retries=1, backoff=1.5, headers=None):
    """GET a URL and return (text, error) without assuming JSON. Used by
    generic_search.py / company_careers.py for PUBLIC_WEB sources that have
    no JSON API — parsing the HTML itself is a future integration point for
    a browser-capable session (see README 'How to add a new source').
    """
    headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    last_error = f"HTTP {resp.status}"
                else:
                    return resp.read().decode("utf-8", errors="replace"), None
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            last_error = f"URLError: {e.reason}"
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(backoff ** attempt)
    return None, last_error
