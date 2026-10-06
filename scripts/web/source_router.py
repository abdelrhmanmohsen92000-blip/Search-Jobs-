"""Source router — identifies which job board/platform a URL belongs to.

Never assumes an unrecognized domain is a known source: unmatched URLs
return source_name="Unknown", source_type="UNKNOWN", confidence=0.0.
"""
import urllib.parse

# (domain substring, source_name, source_type, requires_browser)
_KNOWN_DOMAINS = [
    ("linkedin.com", "LinkedIn", "job_board", True),
    ("indeed.com", "Indeed", "job_board", False),
    ("bayt.com", "Bayt", "job_board", False),
    ("gulftalent.com", "GulfTalent", "job_board", False),
    ("naukrigulf.com", "Naukrigulf", "job_board", False),
    ("glassdoor.com", "Glassdoor", "job_board", True),
    ("wellfound.com", "Wellfound", "job_board", False),
    ("angel.co", "Wellfound", "job_board", False),
    ("remoteok.com", "Remote OK", "job_board", False),
    ("remotive.com", "Remotive", "job_board", False),
    ("weworkremotely.com", "We Work Remotely", "job_board", False),
    ("contra.com", "Contra", "freelance_platform", False),
    ("upwork.com", "Upwork", "freelance_platform", True),
    ("freelancer.com", "Freelancer", "freelance_platform", False),
    ("peopleperhour.com", "PeoplePerHour", "freelance_platform", False),
    ("fiverr.com", "Fiverr", "freelance_platform", False),
    ("archdaily.com", "ArchDaily Jobs", "job_board", False),
]

_CAREERS_PATH_HINTS = ("career", "jobs", "join-us", "work-with-us", "vacanc", "recruit")


def _domain(url):
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:  # noqa: BLE001
        return ""


def identify_source(url):
    """Returns {source_name, source_type, requires_browser, confidence}.

    confidence is 1.0 for an exact known-domain match, a lower heuristic
    value for a plausible company-careers-page guess, and 0.0 for Unknown —
    never asserted as certain when it isn't.
    """
    if not url:
        return {"source_name": "Unknown", "source_type": "UNKNOWN", "requires_browser": False, "confidence": 0.0}

    domain = _domain(url)
    path = urllib.parse.urlparse(url).path.lower()

    for needle, name, source_type, requires_browser in _KNOWN_DOMAINS:
        if needle in domain:
            return {"source_name": name, "source_type": source_type, "requires_browser": requires_browser, "confidence": 1.0}

    if any(hint in path for hint in _CAREERS_PATH_HINTS) or any(hint in domain for hint in _CAREERS_PATH_HINTS):
        return {"source_name": "Company Career Page", "source_type": "company_source", "requires_browser": False, "confidence": 0.5}

    return {"source_name": "Unknown", "source_type": "UNKNOWN", "requires_browser": False, "confidence": 0.0}
