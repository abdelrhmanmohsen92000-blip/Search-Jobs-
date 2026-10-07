"""schema.org JobPosting (JSON-LD) extraction for real job and career pages (Phase 5).

Most employer career sites and ATS platforms publish each vacancy as
schema.org JobPosting structured data for search engines. Reading that is far
more reliable than site-specific CSS selectors, and every field it yields is
stated by the page itself. Nothing is inferred:

    - no JobPosting on the page      -> NO_STRUCTURED_DATA (no opportunity created)
    - JSON-LD present but unreadable -> PARSER_FAILED
    - a field absent from the data   -> None / "UNKNOWN", never guessed
    - employmentType INTERN/VOLUNTEER/PER_DIEM/OTHER -> employment_type None
    - remote only when jobLocationType == TELECOMMUTE (otherwise None, not False)

Closure is only set from explicit evidence: a past `validThrough` date or an
explicit "no longer available"-style statement on the page.
"""
import dataclasses
import datetime as _dt
import html as _html
import json
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

EXTRACTION_METHOD = "json_ld_jobposting"

_EMPLOYMENT_TYPES = {
    "FULL_TIME": "Full-time", "PART_TIME": "Part-time",
    "CONTRACTOR": "Contract", "TEMPORARY": "Contract",
}
_SALARY_PERIODS = {"YEAR": "year", "MONTH": "month", "WEEK": None, "DAY": "day", "HOUR": "hour"}
# Only the countries this system targets are expanded; any other code is kept as given.
_COUNTRY_CODES = {"SA": "Saudi Arabia", "AE": "United Arab Emirates", "QA": "Qatar", "EG": "Egypt",
                  "KW": "Kuwait", "BH": "Bahrain", "OM": "Oman", "JO": "Jordan",
                  "GB": "United Kingdom", "US": "United States"}
CLOSED_PHRASES = (
    "position closed", "position has been filled", "job is no longer available",
    "job no longer available", "no longer accepting applications", "applications closed",
    "applications are closed", "this job has expired", "vacancy closed", "this position is no longer available",
)
_JOB_LINK_RE = re.compile(r"/(?:jobs?|careers?|vacanc(?:y|ies)|positions?|openings?|job-details?)/[^/?#]+", re.I)


@dataclasses.dataclass
class JobPageParseResult:
    status: str  # PARSED / NO_STRUCTURED_DATA / PARSER_FAILED
    opportunities: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    page_closed: bool = False
    json_ld_blocks: int = 0
    json_ld_errors: int = 0


class _PageScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.json_ld, self.links, self.text = [], [], []
        self._in_json_ld = self._in_skip = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._in_json_ld, self._buf = True, []
        elif tag in ("script", "style", "noscript"):
            self._in_skip = True
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._buf))
            self._in_json_ld = False
        elif tag in ("script", "style", "noscript"):
            self._in_skip = False

    def handle_data(self, data):
        if self._in_json_ld:
            self._buf.append(data)
        elif not self._in_skip:
            self.text.append(data)


def scan_page(html_text):
    scanner = _PageScanner()
    try:
        scanner.feed(html_text or "")
        scanner.close()
    except Exception:  # noqa: BLE001 - malformed markup must never crash acquisition
        pass
    return scanner


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", _html.unescape(str(text)))
    return re.sub(r"\s+", " ", text).strip()


def page_says_closed(page_text):
    lowered = (page_text or "").lower()
    return any(p in lowered for p in CLOSED_PHRASES)


def _types(obj):
    t = obj.get("@type")
    return t if isinstance(t, list) else [t]


def find_job_postings(obj):
    found = []
    if isinstance(obj, list):
        for item in obj:
            found += find_job_postings(item)
    elif isinstance(obj, dict):
        if "JobPosting" in _types(obj):
            found.append(obj)
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in obj:
                found += find_job_postings(obj[key])
    return found


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _name(value):
    value = _first(value)
    if isinstance(value, dict):
        return value.get("name")
    return value if isinstance(value, str) else None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return _dt.date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


def _location(posting):
    loc = _first(posting.get("jobLocation"))
    address = loc.get("address") if isinstance(loc, dict) else None
    if not isinstance(address, dict):
        return None, None
    country = _name(address.get("addressCountry"))
    if country and len(country) == 2:
        country = _COUNTRY_CODES.get(country.upper(), country.upper())
    return (country or None), (address.get("addressLocality") or None)


def _employment_type(posting):
    raw = posting.get("employmentType")
    values = raw if isinstance(raw, list) else [raw]
    for v in values:
        mapped = _EMPLOYMENT_TYPES.get(str(v or "").strip().upper().replace("-", "_").replace(" ", "_"))
        if mapped:
            return mapped
    return None


def _salary(posting):
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return {}
    value = base.get("value") if isinstance(base.get("value"), dict) else {}
    low = value.get("minValue", value.get("value"))
    high = value.get("maxValue", value.get("value"))
    if low is None and high is None:
        return {}
    return {
        "salary_min": low, "salary_max": high, "salary_currency": base.get("currency"),
        "salary_period": _SALARY_PERIODS.get(str(value.get("unitText") or "").upper()),
        "salary_source": "posting", "salary_confidence": "OBSERVED",
    }


def jobposting_to_raw(posting, page_url, source_name, company_hint=None, retrieved_at=None, today=None):
    """One JobPosting -> a raw opportunity dict for scripts/lib/normalize.py.
    Returns None when the posting has no title (not a usable job record)."""
    title = strip_html(posting.get("title"))
    if not title:
        return None
    today = today or _dt.date.today()
    retrieved_at = retrieved_at or _dt.datetime.now().isoformat(timespec="seconds")
    company = _name(posting.get("hiringOrganization"))
    country, city = _location(posting)
    job_page_url = posting.get("url") if isinstance(posting.get("url"), str) else page_url
    closing_date = _date(posting.get("validThrough"))

    confidence = 0.9
    if not company:
        company, confidence = company_hint, 0.75  # the page belongs to this company's own careers site
    if not country and not city and posting.get("jobLocationType") != "TELECOMMUTE":
        confidence -= 0.15

    raw = {
        "source": source_name,
        "source_url": job_page_url,
        "job_page_url": job_page_url,
        "application_url": job_page_url if posting.get("directApply") is True else "UNKNOWN",
        "job_title": title,
        "company": company or "",
        "country": country,
        "city": city,
        "remote": True if posting.get("jobLocationType") == "TELECOMMUTE" else None,
        "employment_type": _employment_type(posting),
        "description": strip_html(posting.get("description"))[:4000] or None,
        "date_posted": _date(posting.get("datePosted")),
        "closing_date": closing_date,
        "confidence_score": round(confidence * 100),
        "provenance": {"source": source_name, "source_url": job_page_url, "search_query": None,
                       "retrieved_at": retrieved_at, "extraction_method": EXTRACTION_METHOD,
                       "confidence": round(confidence, 2)},
        "risk_flags": [],
        **_salary(posting),
    }
    if closing_date and closing_date < today.isoformat():
        raw["risk_flags"].append(f"closed: validThrough {closing_date} has passed")
    return raw


def parse_job_page(html_text, page_url, source_name, company_hint=None, retrieved_at=None, today=None):
    scanner = scan_page(html_text)
    blocks = scanner.json_ld
    errors, postings = 0, []
    for block in blocks:
        try:
            postings += find_job_postings(json.loads(block.strip()))
        except (json.JSONDecodeError, ValueError):
            errors += 1
    closed = page_says_closed(" ".join(scanner.text))
    opportunities = []
    for p in postings:
        raw = jobposting_to_raw(p, page_url, source_name, company_hint, retrieved_at, today)
        if raw is None:
            continue
        if closed:
            raw["risk_flags"].append("closed: page states the vacancy is closed")
        opportunities.append(raw)
    if opportunities:
        status = "PARSED"
    elif blocks and errors == len(blocks):
        status = "PARSER_FAILED"
    else:
        status = "NO_STRUCTURED_DATA"
    return JobPageParseResult(status, opportunities, closed, len(blocks), errors)


def _registered_host(host):
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def extract_job_links(html_text, base_url, limit=10):
    """Candidate job-detail links on a careers page: same site (any
    subdomain), path looks like an individual job. Bounded by `limit`."""
    base = urllib.parse.urlparse(base_url)
    out = []
    for href in scan_page(html_text).links:
        url = urllib.parse.urljoin(base_url, href.strip())
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if _registered_host(parsed.netloc) != _registered_host(base.netloc):
            continue
        if not _JOB_LINK_RE.search(parsed.path):
            continue
        clean = urllib.parse.urlunparse(parsed._replace(fragment=""))
        if clean.rstrip("/") == base_url.rstrip("/") or clean in out:
            continue
        out.append(clean)
        if len(out) >= limit:
            break
    return out
