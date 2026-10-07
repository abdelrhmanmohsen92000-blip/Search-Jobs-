"""Multi-mode opportunity classification (Phase 4.2).

One canonical opportunity can belong to several career search modes at once
(a remote full-time role is both FULL_TIME and REMOTE_FULL_TIME). This module
derives those modes deterministically, and ONLY from explicit evidence:

    - the structured `employment_type` field ("Full-time", "Contract", ...)
    - the structured `remote` field (True only — False/None says nothing)
    - explicit phrases in the title/description ("full-time", "6-month
      contract", "freelance", "fully remote", ...)

"Architect needed" therefore classifies as nothing (primary_mode UNKNOWN),
never as a guessed FULL_TIME. The search mode that happened to discover a job
is provenance (`discovered_via_modes`), never evidence, and is never copied
into `matched_modes`.

Merging only ever adds modes/reasons — rediscovering a job through a weaker
or different search can never remove evidence an earlier discovery found.
"""
import re

UNKNOWN = "UNKNOWN"
DEFAULT_PRECEDENCE = ("REMOTE_FULL_TIME", "FULL_TIME", "FREELANCE", "PART_TIME", "CONTRACT")

_EMPLOYMENT_FIELD_MODES = {
    "full-time": "FULL_TIME",
    "part-time": "PART_TIME",
    "contract": "CONTRACT",
    "freelance": "FREELANCE",
    "project-based": "FREELANCE",
}

_FULL_TIME_RE = re.compile(r"\bfull[\s-]?time\b", re.I)
_PART_TIME_RE = re.compile(r"\bpart[\s-]?time\b", re.I)
_FREELANCE_RE = re.compile(r"\bfreelance(?:r)?\b", re.I)
# A bare "contract" is NOT evidence — architecture postings routinely mention
# "contract documents"/"contract drawings". Only employment-contract phrasing counts.
_CONTRACT_RE = re.compile(
    r"\b\d+[\s-]?(?:month|week|year)s?[\s-]+contract\b"
    r"|\bcontract[\s-]+(?:role|position|job|basis|assignment|opportunity|to[\s-]hire)\b"
    r"|\bon\s+a\s+contract\b|\bfixed[\s-]term\b|\(contract\)",
    re.I,
)
# Same caution for remote: "remote project sites" is not a remote job.
_REMOTE_TITLE_RE = re.compile(r"\bremote\b", re.I)
_REMOTE_TEXT_RE = re.compile(
    r"\bfully[\s-]remote\b|\b100%\s*remote\b|\bwork(?:ing)?\s+remotely\b"
    r"|\bremote[\s-]+(?:role|position|job|work|working|first|only|friendly|opportunity)\b"
    r"|\bremote[\s,/-]+(?:full|part)[\s-]?time\b|\b(?:full|part)[\s-]?time[\s,/-]+remote\b",
    re.I,
)


def _precedence(precedence):
    return tuple(precedence) if precedence else DEFAULT_PRECEDENCE


def _ordered(modes, precedence=None):
    order = _precedence(precedence)
    rank = {m: i for i, m in enumerate(order)}
    return sorted(set(modes), key=lambda m: (rank.get(m, len(order)), m))


def _add(reasons, mode, reason):
    bucket = reasons.setdefault(mode, [])
    if reason not in bucket:
        bucket.append(reason)


def classify_modes(opportunity, precedence=None):
    """Returns (matched_modes, mode_match_reasons). Pure function; never
    guesses — an opportunity with no employment-type evidence returns ([], {}).
    """
    reasons = {}
    remote_evidence = []

    employment_type = (opportunity.get("employment_type") or "").strip()
    field_mode = _EMPLOYMENT_FIELD_MODES.get(employment_type.lower())
    if field_mode:
        _add(reasons, field_mode, f"Employment type field explicitly '{employment_type}'")
    if employment_type.lower() == "remote":
        remote_evidence.append("Work mode field explicitly 'Remote'")
    if opportunity.get("remote") is True:
        remote_evidence.append("Structured remote flag is true")

    texts = (("title", opportunity.get("job_title") or ""), ("description", opportunity.get("description") or ""))
    for where, text in texts:
        if not text:
            continue
        if _FULL_TIME_RE.search(text):
            _add(reasons, "FULL_TIME", f"'Full-time' stated in {where}")
        if _PART_TIME_RE.search(text):
            _add(reasons, "PART_TIME", f"'Part-time' stated in {where}")
        if _FREELANCE_RE.search(text):
            _add(reasons, "FREELANCE", f"'Freelance' stated in {where}")
        if _CONTRACT_RE.search(text):
            _add(reasons, "CONTRACT", f"Contract employment stated in {where}")
        remote_re = _REMOTE_TITLE_RE if where == "title" else _REMOTE_TEXT_RE
        if remote_re.search(text):
            remote_evidence.append(f"Remote work stated in {where}")

    if "FULL_TIME" in reasons and remote_evidence:
        for r in reasons["FULL_TIME"]:
            _add(reasons, "REMOTE_FULL_TIME", r)
        for r in remote_evidence:
            _add(reasons, "REMOTE_FULL_TIME", r)

    return _ordered(reasons, precedence), {m: reasons[m] for m in _ordered(reasons, precedence)}


def resolve_primary_mode(matched_modes, precedence=None):
    """Deterministic: the highest-precedence matched mode, or UNKNOWN."""
    ordered = _ordered(matched_modes or [], precedence)
    return ordered[0] if ordered else UNKNOWN


def apply_mode_classification(opportunity, discovered_via_mode=None, precedence=None):
    """Sets matched_modes / primary_mode / mode_match_reasons /
    discovered_via_modes on the opportunity in place and returns it."""
    matched, reasons = classify_modes(opportunity, precedence)
    opportunity["matched_modes"] = matched
    opportunity["mode_match_reasons"] = reasons
    opportunity["primary_mode"] = resolve_primary_mode(matched, precedence)
    discovered = list(opportunity.get("discovered_via_modes") or [])
    if discovered_via_mode and discovered_via_mode not in discovered:
        discovered.append(discovered_via_mode)
    opportunity["discovered_via_modes"] = discovered
    return opportunity


def merge_mode_data(target, other, precedence=None):
    """Folds `other`'s mode data into `target` (the canonical record). Union
    only: nothing target already has is ever removed or downgraded."""
    target["matched_modes"] = _ordered(
        list(target.get("matched_modes") or []) + list(other.get("matched_modes") or []), precedence)
    reasons = {m: list(r) for m, r in (target.get("mode_match_reasons") or {}).items()}
    for mode, mode_reasons in (other.get("mode_match_reasons") or {}).items():
        for r in mode_reasons:
            _add(reasons, mode, r)
    target["mode_match_reasons"] = {m: reasons[m] for m in _ordered(reasons, precedence)}
    discovered = list(target.get("discovered_via_modes") or [])
    for m in other.get("discovered_via_modes") or []:
        if m not in discovered:
            discovered.append(m)
    target["discovered_via_modes"] = discovered
    target["primary_mode"] = resolve_primary_mode(target["matched_modes"], precedence)
    return target


def ensure_mode_defaults(opportunity):
    """Backward compatibility for records written before Phase 4.2."""
    opportunity.setdefault("matched_modes", [])
    opportunity.setdefault("discovered_via_modes", [])
    opportunity.setdefault("mode_match_reasons", {})
    if not opportunity.get("primary_mode"):
        opportunity["primary_mode"] = resolve_primary_mode(opportunity["matched_modes"])
    return opportunity


def serialize_list(values):
    return "|".join(str(v).replace("|", "%7C") for v in (values or []) if str(v))


def parse_list(value):
    if isinstance(value, list):
        return value
    return [v.replace("%7C", "|") for v in (value or "").split("|") if v]
