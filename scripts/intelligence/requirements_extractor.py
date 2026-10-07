"""Job requirements extraction (V1.4).

Turns a normalized opportunity (structured fields + description text) into a
structured requirements profile. Deterministic and local: no network, no LLM.
Every field carries a provenance tag in `field_sources`:

    SOURCE_STRUCTURED  copied from a structured field of the posting (JobPosting / API)
    TEXT_EXTRACTED     found verbatim in the posting text by a deterministic rule
    DERIVED            computed from other extracted fields (e.g. seniority from years)
    AI_DERIVED         added by an optional LLM pass, validated against the text
    UNKNOWN            not stated anywhere — never guessed

Salary, dates and URLs are only ever SOURCE_STRUCTURED; they are never read
out of free text or from an LLM.
"""
import functools
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import paths  # noqa: E402
from scripts.lib.opportunity_modes import classify_modes  # noqa: E402

UNKNOWN = "UNKNOWN"
TAXONOMY_PATH = paths.CONFIG_DIR / "skills_taxonomy.yaml"

_SECTION_PATTERNS = (
    ("responsibilities", re.compile(r"^\s*(key\s+)?(responsibilities|duties|what you('| wi)ll do|the role|role overview)\b", re.I)),
    ("preferred", re.compile(r"^\s*(preferred|nice to have|desirable|bonus|advantageous|good to have)\b", re.I)),
    ("required", re.compile(r"^\s*(requirements?|qualifications?|must have|what you need|skills|essential|"
                            r"about you|minimum qualifications)\b", re.I)),
    ("benefits", re.compile(r"^\s*(benefits?|what we offer|perks|package)\b", re.I)),
)
_PREFERRED_MARKERS = re.compile(r"\b(is a plus|a plus|preferred|nice to have|desirable|advantage(ous)?|bonus|ideally|"
                                r"would be beneficial)\b", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•▪◦]|\d+[.)])\s+")
_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?\+?\s*years?", re.I)
_EDUCATION = re.compile(r"\b(bachelor'?s?|b\.?\s?sc|b\.?\s?arch|master'?s?|m\.?\s?sc|m\.?\s?arch|ph\.?d|doctorate|diploma)"
                        r"(?:\s+degree)?(?:\s+(?:in|of)\s+([A-Za-z ,/&]+?))?(?=[.;\n]|$)", re.I | re.M)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SENIORITY_TITLES = (
    ("DIRECTOR", re.compile(r"\b(director|head of|vp|principal)\b", re.I)),
    ("MANAGER", re.compile(r"\bmanager\b", re.I)),
    ("LEAD", re.compile(r"\b(lead|chief)\b", re.I)),
    ("SENIOR", re.compile(r"\b(senior|sr\.?)\b", re.I)),
    ("JUNIOR", re.compile(r"\b(junior|jr\.?|graduate|entry[- ]level|trainee|intern)\b", re.I)),
)
SENIORITY_ORDER = ("JUNIOR", "MID", "SENIOR", "LEAD", "MANAGER", "DIRECTOR")


@functools.lru_cache(maxsize=None)
def load_taxonomy(path=None):
    path = Path(path) if path else TAXONOMY_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    skills = {}
    for name, spec in (data.get("skills") or {}).items():
        spec = spec or {}
        aliases = sorted({a.lower() for a in (spec.get("aliases") or [])} | {name.lower()}, key=len, reverse=True)
        skills[name] = {"aliases": aliases, "category": spec.get("category", "method"),
                        "transferable_from": list(spec.get("transferable_from") or [])}
    return {
        "skills": skills,
        "certifications": {k: [a.lower() for a in v] for k, v in (data.get("certifications") or {}).items()},
        "languages": list(data.get("languages") or []),
        "benefits": {k: [a.lower() for a in v] for k, v in (data.get("benefits") or {}).items()},
        "eligibility_barriers": list(data.get("eligibility_barriers") or []),
    }


@functools.lru_cache(maxsize=4096)
def _alias_regex(alias):
    return re.compile(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", re.I)


def mentions(text, aliases):
    return any(_alias_regex(a).search(text or "") for a in aliases)


def canonical_skills_in(text, taxonomy=None):
    """Canonical skill names mentioned anywhere in `text` (taxonomy order)."""
    taxonomy = taxonomy or load_taxonomy()
    return [name for name, spec in taxonomy["skills"].items() if mentions(text, spec["aliases"])]


def _split_sections(description):
    """Assigns each line of the description to a section (None = unsectioned)."""
    current, out = None, []
    for raw_line in (description or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header_match = None
        stripped = _BULLET.sub("", line)
        for name, pattern in _SECTION_PATTERNS:
            if pattern.match(stripped) and len(stripped) <= 60:
                header_match = name
                break
        if header_match:
            current = header_match
            remainder = re.split(r":", stripped, maxsplit=1)
            if len(remainder) == 2 and remainder[1].strip():
                out.append((current, remainder[1].strip()))
            continue
        out.append((current, line))
    return out


def _clauses(text):
    return [c.strip() for c in re.split(r"[.;\n]|,(?=\s*[A-Za-z])|\band\b(?=\s+\w+\s+(?:is|are)\b)", text or "") if c.strip()]


def extract_requirements(opportunity, taxonomy=None):
    """Returns the structured requirements profile for one opportunity."""
    taxonomy = taxonomy or load_taxonomy()
    description = opportunity.get("description") or ""
    title = opportunity.get("job_title") or ""
    sections = _split_sections(description)
    sources = {}
    result = {}

    # --- skills: required vs preferred, by section and by clause wording
    required, preferred = [], []
    for section, line in sections:
        if section in ("benefits", "responsibilities"):
            continue
        for clause in _clauses(line):
            found = canonical_skills_in(clause, taxonomy)
            if not found:
                continue
            is_preferred = section == "preferred" or bool(_PREFERRED_MARKERS.search(clause))
            for name in found:
                (preferred if is_preferred else required).append(name)
    # responsibilities mention tools too: count them as required when not already classified
    for section, line in sections:
        if section == "responsibilities":
            for name in canonical_skills_in(line, taxonomy):
                if name not in preferred:
                    required.append(name)
    for name in canonical_skills_in(title, taxonomy):
        required.append(name)
    for structured in (opportunity.get("skills_required") or []) + (opportunity.get("software_required") or []):
        for name in canonical_skills_in(structured, taxonomy):
            required.append(name)
    required = list(dict.fromkeys(required))
    preferred = [p for p in dict.fromkeys(preferred) if p not in required]
    result["required_skills"] = required
    result["preferred_skills"] = preferred
    sources["required_skills"] = "TEXT_EXTRACTED" if required else UNKNOWN
    sources["preferred_skills"] = "TEXT_EXTRACTED" if preferred else UNKNOWN
    software = [s for s in required + preferred if taxonomy["skills"][s]["category"] == "software"]
    result["software"] = software
    sources["software"] = "TEXT_EXTRACTED" if software else UNKNOWN

    # --- responsibilities: bullet lines in a responsibilities section
    responsibilities = [_BULLET.sub("", line).strip() for section, line in sections
                        if section == "responsibilities" and _BULLET.match(line)]
    result["responsibilities"] = responsibilities
    sources["responsibilities"] = "TEXT_EXTRACTED" if responsibilities else UNKNOWN

    # --- years of experience: the figure attached to "experience" wins
    min_years, max_years = None, None
    for m in _YEARS.finditer(description):
        window = description[m.end():m.end() + 40].lower()
        if "experience" in window or "experience" in description[max(0, m.start() - 25):m.start()].lower():
            min_years = int(m.group(1))
            max_years = int(m.group(2)) if m.group(2) else None
            break
    if min_years is None and opportunity.get("experience_required") not in (None, ""):
        try:
            min_years = int(float(str(opportunity["experience_required"]).strip("+ ")))
            sources["min_years_experience"] = "SOURCE_STRUCTURED"
        except ValueError:
            pass
    result["min_years_experience"] = min_years
    result["max_years_experience"] = max_years
    sources.setdefault("min_years_experience", "TEXT_EXTRACTED" if min_years is not None else UNKNOWN)

    # --- education, certifications, languages
    education = []
    for m in _EDUCATION.finditer(description):
        level = m.group(1).strip()
        field = (m.group(2) or "").strip(" ,")
        education.append(f"{level} in {field}" if field else level)
    result["education"] = list(dict.fromkeys(education))
    sources["education"] = "TEXT_EXTRACTED" if education else UNKNOWN

    certs = [name for name, aliases in taxonomy["certifications"].items() if mentions(description, aliases)]
    result["certifications"] = certs
    sources["certifications"] = "TEXT_EXTRACTED" if certs else UNKNOWN

    languages = [lang for lang in taxonomy["languages"] if re.search(rf"\b{lang}\b", description, re.I)]
    result["languages"] = languages
    sources["languages"] = "TEXT_EXTRACTED" if languages else UNKNOWN

    # --- location / work mode / employment type
    location = ", ".join(x for x in (opportunity.get("city"), opportunity.get("country")) if x) or UNKNOWN
    result["location"] = location
    sources["location"] = "SOURCE_STRUCTURED" if location != UNKNOWN else UNKNOWN
    text_all = f"{title}\n{description}"
    if re.search(r"\bhybrid\b", text_all, re.I):
        work_mode, src = "HYBRID", "TEXT_EXTRACTED"
    elif opportunity.get("remote") is True:
        work_mode, src = "REMOTE", "SOURCE_STRUCTURED"
    elif re.search(r"\b(fully remote|100% remote|remote[- ](first|only|role|position|job)|work remotely)\b|^remote\b",
                   text_all, re.I | re.M):
        work_mode, src = "REMOTE", "TEXT_EXTRACTED"
    elif re.search(r"\b(on[- ]site|onsite|in[- ]office|office[- ]based)\b", text_all, re.I):
        work_mode, src = "ON_SITE", "TEXT_EXTRACTED"
    else:
        work_mode, src = UNKNOWN, UNKNOWN
    result["work_mode"] = work_mode
    sources["work_mode"] = src

    modes, _ = classify_modes(opportunity)
    employment = opportunity.get("employment_type")
    result["employment_type"] = employment or (modes[-1] if modes else UNKNOWN)
    sources["employment_type"] = "SOURCE_STRUCTURED" if employment else ("TEXT_EXTRACTED" if modes else UNKNOWN)
    result["employment_modes"] = modes

    # --- salary / benefits (salary only from structured fields)
    if opportunity.get("salary_min") is not None or opportunity.get("salary_max") is not None:
        result["salary"] = {k: opportunity.get(k) for k in ("salary_min", "salary_max", "salary_currency", "salary_period")}
        sources["salary"] = "SOURCE_STRUCTURED"
    else:
        result["salary"] = UNKNOWN
        sources["salary"] = UNKNOWN
    benefits = [name for name, aliases in taxonomy["benefits"].items() if mentions(description, aliases)]
    result["benefits"] = benefits
    sources["benefits"] = "TEXT_EXTRACTED" if benefits else UNKNOWN

    # --- eligibility barriers and visa
    barriers = [b["label"] for b in taxonomy["eligibility_barriers"] if re.search(b["pattern"], description, re.I)]
    result["eligibility_barriers"] = barriers
    sources["eligibility_barriers"] = "TEXT_EXTRACTED" if barriers else UNKNOWN

    # --- company / department / seniority / application method
    result["company"] = opportunity.get("company") or UNKNOWN
    sources["company"] = "SOURCE_STRUCTURED" if opportunity.get("company") else UNKNOWN
    dept = re.search(r"\b(?:join|in) (?:our|the) ([A-Z][\w&]*(?: [A-Z][\w&]*){0,3}) (?:department|team)\b", description)
    result["department"] = dept.group(1) if dept else UNKNOWN
    sources["department"] = "TEXT_EXTRACTED" if dept else UNKNOWN

    seniority, src = None, UNKNOWN
    for level, pattern in _SENIORITY_TITLES:
        if pattern.search(title):
            seniority, src = level, "TEXT_EXTRACTED"
            break
    if seniority is None and min_years is not None:
        seniority = ("JUNIOR" if min_years < 2 else "MID" if min_years < 5 else "SENIOR" if min_years < 10 else "LEAD")
        src = "DERIVED"
    result["seniority"] = seniority or UNKNOWN
    sources["seniority"] = src

    app_url = opportunity.get("application_url")
    email = _EMAIL.search(description)
    if app_url and app_url != UNKNOWN:
        method, src = f"ONLINE: {app_url}", "SOURCE_STRUCTURED"
    elif email:
        method, src = f"EMAIL: {email.group(0)}", "TEXT_EXTRACTED"
    elif re.search(r"careers? (page|portal|site)", description, re.I):
        method, src = "COMPANY_CAREERS_PAGE (URL not stated)", "TEXT_EXTRACTED"
    else:
        method, src = UNKNOWN, UNKNOWN
    result["application_method"] = method
    sources["application_method"] = src

    result["field_sources"] = sources
    return result


def candidate_skill_set(profile, taxonomy=None):
    """Canonical skills the candidate demonstrably has, from config/profile_skills.yaml
    (skills, software, verified_capabilities). Never adds anything not listed there."""
    taxonomy = taxonomy or load_taxonomy()
    texts = list(profile.get("skills") or [])
    texts += [s["name"] if isinstance(s, dict) else s for s in profile.get("software") or []]
    texts += [c["name"] if isinstance(c, dict) else c for c in profile.get("verified_capabilities") or []]
    texts += list(profile.get("project_types") or [])
    have = set()
    for t in texts:
        have.update(canonical_skills_in(t, taxonomy))
    return have


def skills_gap(requirements, profile, taxonomy=None):
    """MATCHED / TRANSFERABLE / MISSING for required and preferred skills."""
    taxonomy = taxonomy or load_taxonomy()
    have = candidate_skill_set(profile, taxonomy)
    out = {"matched": [], "transferable": [], "missing": [], "preferred_matched": [], "preferred_missing": []}
    for skill in requirements.get("required_skills") or []:
        if skill in have:
            out["matched"].append(skill)
        elif set(taxonomy["skills"][skill]["transferable_from"]) & have:
            via = sorted(set(taxonomy["skills"][skill]["transferable_from"]) & have)
            out["transferable"].append({"skill": skill, "via": via})
        else:
            out["missing"].append(skill)
    for skill in requirements.get("preferred_skills") or []:
        (out["preferred_matched"] if skill in have else out["preferred_missing"]).append(skill)
    gaps = out["missing"] + [t["skill"] for t in out["transferable"]] + out["preferred_missing"]
    out["priority_learning"] = list(dict.fromkeys(out["missing"] + [t["skill"] for t in out["transferable"]]
                                                  + out["preferred_missing"]))
    out["has_gaps"] = bool(gaps)
    return out
