"""Deterministic + fuzzy deduplication for opportunity records."""
import difflib
import hashlib
import re


def _norm(text):
    if not text:
        return ""
    text = str(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_id(company, title, location, source_url):
    """Deterministic id: stable hash of normalized company+title+location+source_url."""
    key = "|".join(_norm(x) for x in (company, title, location, source_url))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def exact_key(opportunity):
    return (
        _norm(opportunity.get("company")),
        _norm(opportunity.get("job_title")),
        _norm(opportunity.get("city") or opportunity.get("country")),
        _norm(opportunity.get("source_url")),
    )


def fuzzy_match(a, b, threshold=0.85):
    """True if two opportunities look like the same posting, via fuzzy
    matching on company+title (location must still match exactly, since a
    fuzzy location match is too risky)."""
    if _norm(a.get("city") or a.get("country")) != _norm(b.get("city") or b.get("country")):
        return False
    text_a = f"{_norm(a.get('company'))} {_norm(a.get('job_title'))}"
    text_b = f"{_norm(b.get('company'))} {_norm(b.get('job_title'))}"
    if not text_a or not text_b:
        return False
    ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
    return ratio >= threshold


def deduplicate(opportunities, fuzzy_threshold=0.85):
    """Returns (unique, duplicates) lists, preserving the first-seen record
    for each distinct opportunity. `duplicates` entries are the dropped dicts.
    """
    unique = []
    duplicates = []
    seen_exact = set()

    for opp in opportunities:
        key = exact_key(opp)
        if key in seen_exact:
            duplicates.append(opp)
            continue
        is_fuzzy_dup = any(fuzzy_match(opp, existing, fuzzy_threshold) for existing in unique)
        if is_fuzzy_dup:
            duplicates.append(opp)
            continue
        seen_exact.add(key)
        unique.append(opp)

    return unique, duplicates
