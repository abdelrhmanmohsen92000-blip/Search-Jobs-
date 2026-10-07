"""Canonical error-type classification for source adapters (Phase 4).

scripts/sources/base.py's http_get_json/http_get_text already return honest
free-text error strings ("HTTP 403: Forbidden", "URLError: ..."). This module
maps that free text (plus a SourceRunResult's own status) onto a small,
closed set of canonical error types so callers (source health, the research
summary, tests) can branch on a stable value instead of parsing prose.

This never invents a cause: anything that doesn't match a known pattern is
PROVIDER_ERROR (a real failure happened, its exact shape just isn't one of
the classified ones) rather than a guess like NETWORK_ERROR.
"""
import re

ERROR_TYPES = (
    "TIMEOUT", "HTTP_403", "HTTP_401", "RATE_LIMITED", "AUTH_REQUIRED",
    "NETWORK_ERROR", "PARSER_ERROR", "INVALID_RESPONSE", "PROVIDER_ERROR",
    "BROWSER_REQUIRED", "NO_RESULTS", "SEARCH_PROVIDER_UNAVAILABLE",
)

_HTTP_CODE_RE = re.compile(r"HTTP (\d{3})")

_RATE_LIMIT_MARKERS = ("429", "rate limit", "too many requests")
_TIMEOUT_MARKERS = ("timeout", "timed out")
_NETWORK_MARKERS = ("urlerror", "connection", "connect_rejected", "dns", "name or service not known", "network")
_AUTH_MARKERS = ("401", "unauthorized", "auth_required", "login required", "authentication")
_PARSER_MARKERS = ("parseerror", "parse error", "parser_error", "parser error", "jsondecodeerror", "htmlparse")
_INVALID_RESPONSE_MARKERS = ("malformed", "invalid response", "unexpected format")


def classify_error(status=None, error=None):
    """Returns a canonical error_type for a source-adapter outcome.

    status: the adapter's own SourceRunResult.status (e.g. SUCCESS, EMPTY,
        BROWSER_REQUIRED, UNAVAILABLE, ERROR, NOT_IMPLEMENTED).
    error: the free-text error string, if any.

    Returns None for a genuinely successful/non-error outcome (SUCCESS,
    EMPTY with no error) — never fabricates an error type where none occurred.
    """
    if status == "BROWSER_REQUIRED":
        return "BROWSER_REQUIRED"
    if status == "EMPTY" and not error:
        return "NO_RESULTS"
    if status == "SEARCH_PROVIDER_UNAVAILABLE":
        return "SEARCH_PROVIDER_UNAVAILABLE"
    if status in ("SUCCESS",) and not error:
        return None
    if not error:
        return None

    text = error.lower()

    code_match = _HTTP_CODE_RE.search(error)
    if code_match:
        code = code_match.group(1)
        if code == "403":
            return "HTTP_403"
        if code == "401":
            return "HTTP_401"
        if code == "429":
            return "RATE_LIMITED"

    if any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return "RATE_LIMITED"
    if any(marker in text for marker in _TIMEOUT_MARKERS):
        return "TIMEOUT"
    if any(marker in text for marker in _AUTH_MARKERS):
        return "AUTH_REQUIRED"
    if any(marker in text for marker in _PARSER_MARKERS):
        return "PARSER_ERROR"
    if any(marker in text for marker in _INVALID_RESPONSE_MARKERS):
        return "INVALID_RESPONSE"
    if any(marker in text for marker in _NETWORK_MARKERS):
        return "NETWORK_ERROR"

    return "PROVIDER_ERROR"
