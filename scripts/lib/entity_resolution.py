"""Company entity resolution.

Resolves superficial name variants ("Al Futtaim" / "Al-Futtaim" / "Al Futtaim
Group") to one canonical form, but only when confidence is high: the
canonicalization strips case, punctuation, and a small set of common
corporate suffixes, and two names are only merged when their canonical keys
match EXACTLY. This deliberately never fuzzy-merges two different company
names that merely look similar — "Al Futtaim" and "Al Futtan" stay distinct.
"""
import re

_SUFFIXES = [
    "group", "llc", "l.l.c", "inc", "incorporated", "ltd", "limited", "co",
    "company", "corp", "corporation", "holding", "holdings", "plc",
]
_SUFFIX_RE = re.compile(r"\b(" + "|".join(re.escape(s) for s in _SUFFIXES) + r")\b\.?", re.I)


def canonical_key(name):
    """Normalized lookup key: lowercase, punctuation stripped, common
    corporate suffixes removed, whitespace collapsed. Used only for exact
    matching — never compared with fuzzy ratios.
    """
    if not name:
        return ""
    key = name.lower()
    key = re.sub(r"[.\-_/&,]", " ", key)
    key = _SUFFIX_RE.sub(" ", key)
    key = re.sub(r"[^a-z0-9\s]", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return key


def resolve_companies(names):
    """names: iterable of company name strings (as they appear in records).

    Returns a dict {original_name: canonical_name} where canonical_name is
    the longest original spelling among all names sharing a canonical_key
    (a readable, real spelling, not the stripped key itself). Names whose
    canonical_key is empty (e.g. blank) are mapped to themselves, never
    merged with anything.
    """
    groups = {}
    for name in names:
        if not name or not name.strip():
            continue
        key = canonical_key(name)
        if not key:
            continue
        groups.setdefault(key, []).append(name)

    mapping = {}
    for key, variants in groups.items():
        canonical = max(set(variants), key=lambda v: (len(v), v))
        for v in variants:
            mapping[v] = canonical
    return mapping


def resolve_company(name, known_names=None):
    """Resolve a single name against a pool of already-known names (e.g.
    tracking/companies.csv company_name column). Returns the canonical form
    from known_names if one shares its canonical_key with high confidence
    (exact key match), else returns name unchanged.
    """
    if not name or not known_names:
        return name
    key = canonical_key(name)
    if not key:
        return name
    for known in known_names:
        if canonical_key(known) == key:
            return known if len(known) >= len(name) else name
    return name
