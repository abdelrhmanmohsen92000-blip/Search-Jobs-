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
    http_status: Optional[int] = None
    requests_made: int = 0

    def to_dict(self):
        return dataclasses.asdict(self)


class SourceAdapter:
    name = "base"
    access_type = "UNKNOWN"  # API / PUBLIC_WEB / BROWSER_REQUIRED / MANUAL

    def fetch(self, query=None, limit=None) -> SourceRunResult:
        raise NotImplementedError


_RETRYABLE_HTTP = {500, 502, 503, 504}


def _is_retryable(status, error):
    """Only transient failures are retried (timeouts, network errors, 5xx).
    A 4xx — and a proxy that refuses the CONNECT tunnel with 403 — is a
    deliberate refusal; retrying it just hammers the host (Phase 5 §29)."""
    if status is not None:
        return status in _RETRYABLE_HTTP
    text = (error or "").lower()
    return not any(marker in text for marker in ("403", "401", "407", "429", "forbidden", "unauthorized"))


def http_fetch(url, timeout=10, retries=1, backoff=1.5, headers=None):
    """GET a URL. Returns (body_bytes, error, http_status). Never raises.
    http_status is the real response code when one was received, else None
    (DNS failure, refused tunnel, timeout)."""
    from scripts.lib import runtime
    if runtime.is_offline():  # NETWORK_MODE=offline: never touch the network
        return None, "NETWORK_OFFLINE: NETWORK_MODE=offline", None
    headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error, last_status = None, None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                last_status = resp.status
                if resp.status == 200:
                    return resp.read(), None, 200
                last_error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            last_status, last_error = e.code, f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            last_status, last_error = None, f"URLError: {e.reason}"
        except Exception as e:  # noqa: BLE001 - adapters must never crash the pipeline
            last_status, last_error = None, f"{type(e).__name__}: {e}"
        if attempt < retries and _is_retryable(last_status, last_error):
            time.sleep(backoff ** attempt)
            continue
        break
    return None, last_error, last_status


def http_get_json(url, timeout=10, retries=2, backoff=1.5, headers=None):
    """GET a URL and parse JSON, with timeout + bounded retry on transient
    failures only. Returns (data, error). Never raises: on failure returns
    (None, "<reason>") so callers report an honest status instead of crashing.
    """
    body, error, _ = http_fetch(url, timeout, retries, backoff,
                                {"Accept": "application/json", **(headers or {})})
    if error:
        return None, error
    try:
        return json.loads(body), None
    except json.JSONDecodeError as e:
        return None, f"JSONDecodeError: {e}"


def http_get_text(url, timeout=10, retries=1, backoff=1.5, headers=None):
    """GET a URL and return (text, error) without assuming JSON (HTML pages).
    Same transient-only retry policy as http_get_json."""
    body, error, _ = http_fetch(url, timeout, retries, backoff, headers)
    if error:
        return None, error
    return body.decode("utf-8", errors="replace"), None
