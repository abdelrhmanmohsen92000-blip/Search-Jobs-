"""Generic web page extraction — stdlib only, no JS rendering.

Pulls page title, visible text, headings, and links from raw HTML, then
makes best-effort, regex-based guesses at job-posting fields (company,
title, location, employment type, remote, salary, skills). Every guess is
either grounded in matched text or left as None — nothing is invented.

If the page looks JS-rendered (near-empty body, a known SPA-shell marker),
returns PAGE_STATUS = JS_REQUIRED instead of guessing from nothing.
"""
import re
from html.parser import HTMLParser

from scripts.web.base import PageExtractionResult

_JS_SHELL_MARKERS = (
    "you need to enable javascript",
    "please enable javascript",
    "noscript",
    "id=\"root\"></div>",
    "id=\"app\"></div>",
)

_EMPLOYMENT_TYPE_PATTERNS = [
    (r"\bfull[\s-]?time\b", "Full-time"),
    (r"\bpart[\s-]?time\b", "Part-time"),
    (r"\bfreelance\b", "Freelance"),
    (r"\bcontract\b", "Contract"),
    (r"\bremote\b", "Remote"),
    (r"\bhybrid\b", "Hybrid"),
    (r"\bon[\s-]?site\b", "On-site"),
    (r"\bproject[\s-]?based\b", "Project-based"),
]

_KNOWN_SOFTWARE = ["Revit", "Navisworks", "AutoCAD", "BIM 360", "ACC", "3ds Max", "SketchUp", "Rhino", "Lumion"]
_KNOWN_SKILLS = ["BIM Coordination", "Clash Coordination", "Shop Drawings", "Construction Documentation",
                 "Architectural Visualization", "Facade Design", "Master Planning", "Landscape Design"]

_SALARY_RE = re.compile(r"(?:USD|EUR|GBP|AED|SAR|\$|€|£)\s?[\d,]{3,}(?:\s?-\s?(?:USD|EUR|GBP|AED|SAR|\$|€|£)?\s?[\d,]{3,})?", re.I)
_LOCATION_HINT_RE = re.compile(r"(?:location|based in|office in)\s*[:\-]?\s*([A-Za-z\s,]{2,40})", re.I)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.in_title = False
        self.headings = []
        self._current_heading = None
        self.links = []
        self.text_parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag in ("h1", "h2", "h3"):
            self._current_heading = []
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in ("h1", "h2", "h3") and self._current_heading is not None:
            text = "".join(self._current_heading).strip()
            if text:
                self.headings.append(text)
            self._current_heading = None
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        if self.in_title:
            self.title_parts.append(data)
        if self._current_heading is not None:
            self._current_heading.append(data)
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def _find_first(patterns_with_labels, text):
    for pattern, label in patterns_with_labels:
        if re.search(pattern, text, re.I):
            return label
    return None


def _looks_js_rendered(html, text):
    lowered = html.lower()
    if any(marker in lowered for marker in _JS_SHELL_MARKERS):
        return True
    if len(text.strip()) < 200 and len(html) > 2000:
        return True
    return False


def extract_from_html(html, url=None):
    """Returns a PageExtractionResult. Never fabricates a field it can't
    find in the text — unmatched fields stay None/[].
    """
    if not html or not html.strip():
        return PageExtractionResult(status="PARSE_ERROR", url=url, error="Empty HTML")

    try:
        parser = _TextExtractor()
        parser.feed(html)
    except Exception as e:  # noqa: BLE001
        return PageExtractionResult(status="PARSE_ERROR", url=url, error=f"{type(e).__name__}: {e}")

    text = " ".join(parser.text_parts)

    if _looks_js_rendered(html, text):
        return PageExtractionResult(status="JS_REQUIRED", url=url, title="".join(parser.title_parts).strip() or None)

    title = "".join(parser.title_parts).strip() or None
    job_title = parser.headings[0] if parser.headings else None

    employment_type = _find_first(_EMPLOYMENT_TYPE_PATTERNS, text)
    remote = True if employment_type == "Remote" or re.search(r"\bremote\b", text, re.I) else None

    salary_match = _SALARY_RE.search(text)
    salary = salary_match.group(0) if salary_match else None

    location_match = _LOCATION_HINT_RE.search(text)
    location = location_match.group(1).strip().rstrip(".,") if location_match else None

    skills = [s for s in (_KNOWN_SOFTWARE + _KNOWN_SKILLS) if re.search(re.escape(s), text, re.I)]

    application_url = next((link for link in parser.links if re.search(r"apply|application", link, re.I)), None)

    return PageExtractionResult(
        status="OK",
        url=url,
        title=title,
        text=text[:5000] or None,
        headings=parser.headings,
        links=parser.links,
        company=None,  # company name extraction needs structured data (JSON-LD/microdata) not implemented in V1.3 — never guessed from free text
        job_title=job_title,
        location=location,
        employment_type=employment_type,
        remote=remote,
        salary=salary,
        description=text[:2000] or None,
        requirements=[],
        skills=skills,
        application_url=application_url,
    )
