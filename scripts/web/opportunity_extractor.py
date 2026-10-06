"""Search result / page → candidate opportunity.

Converts a SearchResult (and, if available, a PageExtractionResult for the
same URL) into a candidate dict compatible with
schemas/opportunity.schema.json, plus a `provenance` block and a
`confidence_score` (extraction/source reliability — NOT the match score from
scripts/lib/scoring.py, which measures fit to the candidate's profile).

Also implements the rule-based OPEN_VACANCY / FREELANCE_PROJECT /
COMPANY_SIGNAL / IRRELEVANT classifier (Phase 8).
"""
import datetime as _dt
import re

from scripts.web.source_router import identify_source

FREELANCE_PATTERNS = [
    r"\bfreelance(?:r)?\b", r"\bgig\b", r"\bupwork\b", r"\bfiverr\b",
    r"\bproject[\s-]?based\b", r"\bhourly rate\b", r"\bshort[\s-]?term project\b",
]
VACANCY_PATTERNS = [
    r"\bhiring\b", r"\bvacanc(?:y|ies)\b", r"\bwe are looking for\b", r"\bjoin our team\b",
    r"\bapply now\b", r"\bopen position\b", r"\bjob opening\b", r"\bcareers?\b",
    r"\bfull[\s-]?time\b", r"\bpart[\s-]?time\b", r"\bexperience required\b", r"\bresponsibilities\b",
]
COMPANY_SIGNAL_PATTERNS = [
    r"\bwins?\b.*\bproject\b", r"\bawarded\b", r"\bexpands?\b", r"\bopens? (?:a )?new office\b",
    r"\bappoints?\b", r"\bannounces?\b.*\b(?:project|expansion|office)\b", r"\blaunches? new\b",
    r"\bgrowing (?:bim|architecture) team\b", r"\badopts bim\b",
]
JOB_TITLE_WORDS = [
    "architect", "bim", "designer", "coordinator", "revit", "visualizer", "specialist",
]

_COMPANY_NAME_FRAGMENT = r"[A-Z][\w&.,'\-]*(?:\s+(?:[A-Z][\w&.,'\-]*|of|and|&))*"
_COMPANY_FROM_SNIPPET_PATTERNS = [
    rf"\b({_COMPANY_NAME_FRAGMENT})\s+is\s+hiring\b",
    rf"\b({_COMPANY_NAME_FRAGMENT})\s+is\s+looking\s+for\b",
    rf"\b({_COMPANY_NAME_FRAGMENT})\s+seeks\b",
    rf"\bjoin\s+({_COMPANY_NAME_FRAGMENT})\b",
    rf"\bat\s+({_COMPANY_NAME_FRAGMENT})(?:\s+in\b|[.,]|$)",
]
_COMPANY_SIGNAL_VERB_RE = re.compile(
    r"^(.*?)\s+(?:wins?|announces?|expands?|is awarded|has been awarded|appoints?|launches?)\b", re.I
)


def _guess_company_from_text(text):
    """Only returns a company name when a specific textual pattern supports
    it (e.g. "X is hiring", "join X") — never a bare guess from thin air.
    """
    if not text:
        return None
    for pattern in _COMPANY_FROM_SNIPPET_PATTERNS:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip().rstrip(".,")
            if 1 < len(candidate) <= 60:
                return candidate
    return None


def _guess_company_from_signal_title(title):
    """For a COMPANY_SIGNAL headline ("Al Futtaim Group wins major airport
    project"), the company is the text before the signal verb — grounded in
    the title's own structure, not invented.
    """
    if not title:
        return None
    match = _COMPANY_SIGNAL_VERB_RE.match(title.strip())
    if match:
        candidate = match.group(1).strip()
        if candidate:
            return candidate
    return None


def classify(title, snippet=None, description=None):
    """Rule-based classifier: OPEN_VACANCY / FREELANCE_PROJECT / COMPANY_SIGNAL / IRRELEVANT.

    Order matters: freelance language wins over generic vacancy language
    (a freelance BIM gig shouldn't be scored as a full-time vacancy), then
    vacancy, then company-signal, else irrelevant. Never defaults to
    OPEN_VACANCY just because a job-sounding word appears — needs a vacancy
    or title+role-word combination.
    """
    text = " ".join(filter(None, [title, snippet, description])).lower()
    if not text.strip():
        return "IRRELEVANT"

    if any(re.search(p, text) for p in FREELANCE_PATTERNS):
        return "FREELANCE_PROJECT"

    if any(re.search(p, text) for p in VACANCY_PATTERNS):
        return "OPEN_VACANCY"

    # A bare role-sounding title with a location (common search-result shape:
    # "Senior BIM Architect — Dubai") also counts as a vacancy signal even
    # without explicit "hiring" language. Word-boundary matched so "architecture"
    # (a news/article word) never false-positives on "architect".
    title_lower = (title or "").lower()
    has_role_word = any(re.search(rf"\b{re.escape(w)}\b", title_lower) for w in JOB_TITLE_WORDS)
    has_separator = bool(re.search(r"\s[—–-]\s", title or ""))
    if has_role_word and has_separator:
        return "OPEN_VACANCY"

    if any(re.search(p, text) for p in COMPANY_SIGNAL_PATTERNS):
        return "COMPANY_SIGNAL"

    return "IRRELEVANT"


def _confidence_score(search_result, page_result, candidate):
    """0-100. Source reliability + extraction quality + field certainty —
    deliberately separate from the opportunity's match score.
    """
    score = 0
    source_info = identify_source(getattr(search_result, "url", None) or candidate.get("source_url"))
    score += 30 * source_info["confidence"]  # up to 30
    if page_result is not None and getattr(page_result, "status", None) == "OK":
        score += 20
    if candidate.get("job_title"):
        score += 15
    if candidate.get("company"):
        score += 15
    url = candidate.get("source_url") or ""
    if url.startswith("http://") or url.startswith("https://"):
        score += 10
    if candidate.get("description"):
        score += 10
    return round(min(score, 100), 1)


def extract_opportunity(search_result, page_result=None):
    """search_result: a SearchResult (scripts/web/base.py) or dict with the
    same shape. page_result: optional PageExtractionResult for the same URL.

    Returns (candidate_dict, classification) where candidate_dict is ready
    for scripts/lib/normalize.normalize_opportunity(), carrying a
    `provenance` block and `confidence_score`. Returns (None, classification)
    for IRRELEVANT content — callers should not create an opportunity record
    for it, only log the classification.
    """
    sr = search_result if hasattr(search_result, "title") else _DictAsResult(search_result)
    title = sr.title
    snippet = sr.snippet
    url = sr.url

    description = None
    job_title = title
    company = None
    location = None
    country = None
    employment_type = None
    remote = None
    skills = []
    extraction_method = "search_result_only"

    if page_result is not None and getattr(page_result, "status", None) == "OK":
        extraction_method = "page_extraction"
        job_title = page_result.job_title or title
        company = page_result.company
        location = page_result.location
        employment_type = page_result.employment_type
        remote = page_result.remote
        skills = page_result.skills
        description = page_result.description
    else:
        # Guessed from the snippet only (never the title): a title like
        # "BIM Coordinator - Berlin" would otherwise bleed its location into
        # a greedy capitalized-phrase match meant for the snippet's company mention.
        company = _guess_company_from_text(snippet)
        if company:
            extraction_method = "snippet_pattern_match"

    # Classification text includes job_title/employment_type when page
    # extraction supplied them — these are real extracted facts, not
    # fabricated, and a confirmed employment_type (e.g. "Full-time") is
    # itself vacancy evidence a bare search snippet might lack.
    classification_context = " ".join(filter(None, [job_title, snippet, description, employment_type]))
    classification = classify(title, classification_context)
    if classification == "IRRELEVANT":
        return None, classification

    candidate = {
        "source": sr.source or identify_source(url)["source_name"],
        "source_url": url,
        "job_title": job_title or "",
        "company": company or "",  # left empty when truly unknown — normalize/validate will flag it, never guessed
        "country": country,
        "city": None,
        "region": sr.region,
        "remote": remote,
        "employment_type": employment_type,
        "skills_required": skills,
        "description": description or snippet,
        "date_found": _dt.date.today().isoformat(),
    }
    candidate["location_raw"] = location  # not part of the schema; kept for manual review, dropped by normalize()

    candidate["provenance"] = {
        "source": candidate["source"],
        "source_url": url,
        "search_query": sr.query,
        "retrieved_at": sr.timestamp or _dt.datetime.now().isoformat(timespec="seconds"),
        "extraction_method": extraction_method,
        "confidence": None,  # filled in below once confidence_score is computed
    }
    candidate["confidence_score"] = _confidence_score(sr, page_result, candidate)
    candidate["provenance"]["confidence"] = candidate["confidence_score"] / 100

    return candidate, classification


class _DictAsResult:
    """Adapts a plain dict (e.g. loaded straight from JSON) to the
    SearchResult attribute interface, without requiring callers to
    construct a dataclass."""

    def __init__(self, d):
        d = d or {}
        self.title = d.get("title")
        self.url = d.get("url")
        self.snippet = d.get("snippet")
        self.source = d.get("source")
        self.query = d.get("query")
        self.region = d.get("region")
        self.timestamp = d.get("timestamp")
