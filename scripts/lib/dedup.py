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


def attach_duplicates(unique, duplicates, on_merge=None, fuzzy_threshold=0.85):
    """For the (unique, duplicates) output of deduplicate(): folds each
    dropped duplicate back into the canonical record it matched, using the
    same exact-then-fuzzy identity rules — so nothing a duplicate carried
    (its source URL, or via `on_merge(canonical, duplicate)` e.g. its career
    modes) is lost. Never creates or removes canonical records.
    """
    for dup in duplicates:
        key = exact_key(dup)
        canonical = next((c for c in unique if exact_key(c) == key), None)
        if canonical is None:
            canonical = next((c for c in unique if fuzzy_match(dup, c, fuzzy_threshold)), None)
        if canonical is None:
            continue
        alternates = canonical.setdefault("alternate_sources", [])
        entry = {"source": dup.get("source"), "source_url": dup.get("source_url")}
        if dup.get("source_url") != canonical.get("source_url") and entry not in alternates:
            alternates.append(entry)
        if on_merge:
            on_merge(canonical, dup)
    return unique


def merge_duplicates(opportunities, fuzzy_threshold=0.85, on_merge=None):
    """Like deduplicate(), but never loses source information: each dropped
    duplicate's {source, source_url} is appended to the surviving canonical
    record's `alternate_sources` list instead of being discarded outright.
    Used by the web intelligence layer, where the same posting commonly
    shows up on multiple boards (LinkedIn + Indeed + a company careers page).
    on_merge(canonical, duplicate), if given, folds in any other data (e.g.
    Phase 4.2 career modes).

    Returns (canonical_list, dropped_count).
    """
    canonical = []

    for opp in opportunities:
        key = exact_key(opp)
        match = next((c for c in canonical if exact_key(c) == key), None)
        if match is None:
            match = next((c for c in canonical if fuzzy_match(opp, c, fuzzy_threshold)), None)

        if match is None:
            opp.setdefault("alternate_sources", [])
            canonical.append(opp)
            continue

        match.setdefault("alternate_sources", [])
        match["alternate_sources"].append({"source": opp.get("source"), "source_url": opp.get("source_url")})
        if on_merge:
            on_merge(match, opp)

    dropped_count = len(opportunities) - len(canonical)
    return canonical, dropped_count
