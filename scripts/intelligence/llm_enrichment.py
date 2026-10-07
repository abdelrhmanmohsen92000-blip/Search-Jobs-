"""Optional LLM enrichment of extracted requirements (V1.4).

Runs only when config/ai.yaml selects a real LLM provider AND the job clears
the AI cost tier (scripts/intelligence/ai_provider.tier_for_score). The
deterministic extractor always runs first; the LLM can only ADD items, and
every item it proposes is checked against the posting text:

    - list items (skills, responsibilities, certifications, languages) are
      kept only if the phrase appears in the posting
    - seniority is kept only if the word appears in the title/description
    - salary, dates, URLs, company facts and job status are never requested
      from, or accepted from, the model

Accepted items are tagged AI_DERIVED in field_sources; rejected ones are
listed in `rejected_unverifiable` so nothing is silently dropped either.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.intelligence import ai_provider  # noqa: E402
from scripts.intelligence.requirements_extractor import canonical_skills_in, load_taxonomy  # noqa: E402

LIST_FIELDS = ("responsibilities", "required_skills", "preferred_skills", "certifications", "languages")
PROMPT = (
    "Extract the requirements of this job posting. Return a JSON object with exactly these keys: "
    "responsibilities (list of strings), required_skills (list), preferred_skills (list), certifications (list), "
    "languages (list), seniority (one of JUNIOR, MID, SENIOR, LEAD, MANAGER, DIRECTOR, or UNKNOWN), "
    "department (string or UNKNOWN). Copy phrases exactly as they appear in the posting. If something is not "
    "stated, use an empty list or UNKNOWN. Do not infer, do not add anything that is not written in the posting."
)


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def enrich(opportunity, requirements, overall_match, provider=None, ai_config=None):
    """Returns (requirements, llm_info). `requirements` is a new dict with
    verified AI additions merged in; the input is not modified."""
    provider = provider or ai_provider.get_ai_provider(ai_config)
    if getattr(provider, "name", "rule_based") == "rule_based":
        return requirements, {"used": False, "status": "RULE_BASED_ONLY"}
    if ai_provider.tier_for_score(overall_match) < 2:
        return requirements, {"used": False, "status": "BELOW_AI_TIER"}
    description = opportunity.get("description") or ""
    if len(description) < 80:
        return requirements, {"used": False, "status": "NO_POSTING_TEXT"}

    response = provider.analyze(PROMPT, {"job_title": opportunity.get("job_title"), "posting": description[:8000]})
    ok, payload = ai_provider.validate_ai_output(response, required_keys=list(LIST_FIELDS) + ["seniority"])
    if not ok:
        return requirements, {"used": False, "status": payload["status"],
                              "original_status": payload.get("original_status"), "reason": payload.get("reason")}

    text = _norm(f"{opportunity.get('job_title')}\n{description}")
    taxonomy = load_taxonomy()
    merged = {k: (list(v) if isinstance(v, list) else v) for k, v in requirements.items()}
    merged["field_sources"] = dict(requirements.get("field_sources") or {})
    added, rejected = {}, []
    for key in LIST_FIELDS:
        for item in payload.get(key) or []:
            if not isinstance(item, str) or len(item.strip()) < 2 or _norm(item) not in text:
                rejected.append({"field": key, "value": item})
                continue
            values = canonical_skills_in(item, taxonomy) if key.endswith("_skills") else [item.strip()]
            for value in values:
                if value not in merged.get(key, []) and not (key == "preferred_skills" and value in merged["required_skills"]):
                    merged.setdefault(key, []).append(value)
                    added.setdefault(key, []).append(value)
    seniority = str(payload.get("seniority") or "UNKNOWN").upper()
    if merged.get("seniority") in (None, "UNKNOWN") and seniority != "UNKNOWN":
        if seniority.lower() in text:
            merged["seniority"] = seniority
            added["seniority"] = seniority
        else:
            rejected.append({"field": "seniority", "value": seniority})
    for key in added:
        previous = merged["field_sources"].get(key)
        merged["field_sources"][key] = "AI_DERIVED" if previous in (None, "UNKNOWN", "DERIVED") else f"{previous}+AI_DERIVED"
    return merged, {"used": bool(added), "status": "OK", "provider": getattr(provider, "name", None),
                    "model": response.get("model"), "added": added, "rejected_unverifiable": rejected}
