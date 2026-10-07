"""AI analysis & decision engine (V1.4).

For every verified job:

    requirements extraction -> skills gap -> 12 evidence-based dimensions ->
    Overall Match / Opportunity / Confidence scores -> decision + reasons + risks

Dimensions (0-100; application_difficulty is higher = harder):
    profile_match, skills_match, experience_match, location_match,
    employment_match, company_quality, career_growth, compensation,
    freshness, application_difficulty, networking_value, strategic_value

Decisions: APPLY_NOW, APPLY, REVIEW, NETWORK_FIRST, WATCH, SKIP — every one
carries the reasons and risks that produced it. All weights and thresholds come
from the ACTIVE version in config/scoring_model.yaml, and the version used is
stored with every analysis.

Deterministic by default. An optional LLM pass (scripts/intelligence/llm_enrichment.py)
may add requirement items, but only items found in the posting text survive,
and they are tagged AI_DERIVED.
"""
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.intelligence import opportunity_priority, scoring_model  # noqa: E402
from scripts.intelligence.requirements_extractor import (  # noqa: E402
    SENIORITY_ORDER, UNKNOWN, extract_requirements, load_taxonomy, skills_gap)
from scripts.lib import config as cfg_lib, paths, staleness, storage  # noqa: E402
from scripts.lib import opportunity_modes  # noqa: E402

DECISIONS = ("APPLY_NOW", "APPLY", "REVIEW", "NETWORK_FIRST", "WATCH", "SKIP")
DECISION_ICONS = {"APPLY_NOW": "🔥", "APPLY": "🟢", "REVIEW": "🟡", "NETWORK_FIRST": "🔵", "WATCH": "⚪", "SKIP": "🔴"}
# Mapping to the earlier V1.4 decision vocabulary (scripts/intelligence/decision_engine.py).
LEGACY_EQUIVALENT = {"APPLY_NOW": "APPLY_NOW", "APPLY": "APPLY", "REVIEW": "CONSIDER", "NETWORK_FIRST": "NETWORK_FIRST",
                     "WATCH": "LOW_PRIORITY", "SKIP": "SKIP"}

ANALYSES_FIELDNAMES = [
    "analysis_id", "job_id", "company", "job_title", "model_version", "analyzed_at", "decision",
    "overall_match", "opportunity_score", "confidence", "profile_match", "skills_match", "experience_match",
    "location_match", "employment_match", "company_quality", "career_growth", "compensation", "freshness",
    "application_difficulty", "networking_value", "strategic_value", "matched_skills", "missing_skills",
    "transferable_skills", "reasons", "risks", "recommendation", "llm_used",
]

_FRESHNESS_SCORES = {"FRESH": 100, "RECENT": 80, "AGING": 55, "STALE": 25, "CLOSED": 0, "UNKNOWN": 50}
_PORTFOLIO_SCORES = {"STRONG": 100, "DIRECT": 80, "CAPABILITY": 55, "REGIONAL": 40, "NONE": 20, "INSUFFICIENT": 30}


def _clip(x, lo=0, hi=100):
    return max(lo, min(hi, round(x, 1)))


def _profile_level(years):
    return "JUNIOR" if years < 2 else "MID" if years < 5 else "SENIOR" if years < 10 else "LEAD"


# --- individual dimensions -------------------------------------------------------

def _skills_dimension(gap, requirements, software_only=False, taxonomy=None):
    taxonomy = taxonomy or load_taxonomy()

    def keep(skill):
        return (not software_only) or taxonomy["skills"][skill]["category"] == "software"
    matched = [s for s in gap["matched"] if keep(s)]
    transferable = [t for t in gap["transferable"] if keep(t["skill"])]
    missing = [s for s in gap["missing"] if keep(s)]
    total = len(matched) + len(transferable) + len(missing)
    if total == 0:
        return 50.0, ["No explicit " + ("software" if software_only else "skill") + " requirements stated"]
    score = (len(matched) + 0.6 * len(transferable)) / total * 100
    if not software_only:
        score += min(10, 5 * len([s for s in gap["preferred_matched"]]))
    evidence = []
    if matched:
        evidence.append("Matched: " + ", ".join(matched))
    if transferable:
        evidence.append("Transferable: " + ", ".join(f"{t['skill']} (via {'/'.join(t['via'])})" for t in transferable))
    if missing:
        evidence.append("Missing: " + ", ".join(missing))
    return _clip(score), evidence


def _experience_dimension(requirements, candidate_years):
    req = requirements.get("min_years_experience")
    level = requirements.get("seniority")
    if req is None:
        score, evidence = 65.0, ["Years of experience not stated"]
    else:
        gap = req - candidate_years
        if gap <= 0:
            score = 80.0 if candidate_years - req >= 6 else 100.0
            evidence = [f"Requires {req}+ years — you have {candidate_years}"]
        else:
            score = {1: 75.0, 2: 55.0}.get(gap, 35.0 if gap <= 4 else 15.0)
            evidence = [f"Requires {req}+ years — you have {candidate_years} ({gap} short)"]
    if level in ("MANAGER", "DIRECTOR") and candidate_years < 8:
        score = min(score, 35.0)
        evidence.append(f"{level.title()}-level role; your profile is {_profile_level(candidate_years).title()}")
    return _clip(score), evidence


def location_tiers(matrix=None):
    matrix = matrix if matrix is not None else cfg_lib.load_search_matrix()
    tiers = []
    for t in matrix.get("target_locations") or []:
        tiers.append({**t, "match": {loc.lower() for loc in t.get("locations") or []}})
    return tiers


_COUNTRY_SYNONYMS = {"united arab emirates": "uae", "kingdom of saudi arabia": "saudi arabia", "ksa": "saudi arabia"}


def _location_dimension(opportunity, requirements, tiers):
    country = (opportunity.get("country") or "").strip().lower()
    country = _COUNTRY_SYNONYMS.get(country, country)
    city = (opportunity.get("city") or "").strip().lower()
    barriers = requirements.get("eligibility_barriers") or []
    for t in sorted(tiers, key=lambda t: t.get("tier", 99)):
        if (country and country in t["match"]) or (city and city in t["match"]):
            score = 60 + 8 * float(t.get("weight", 1))
            where = ", ".join(x for x in (opportunity.get("city"), opportunity.get("country")) if x)
            return _clip(score), t, [f"{where} — target market tier {t.get('tier')} ({t.get('region')})"]
    if opportunity.get("remote") is True or requirements.get("work_mode") == "REMOTE":
        t = next((t for t in tiers if "remote" in t["match"]), None)
        score = 60 + 8 * float(t.get("weight", 1)) if t else 70
        return _clip(score), t, ["Remote role — compatible with any base location"]
    if not country and not city:
        return 50.0, None, ["Location not stated"]
    if barriers:
        return 20.0, None, [f"{opportunity.get('country') or opportunity.get('city')} — outside target markets, with eligibility barriers"]
    return 45.0, None, [f"{opportunity.get('country') or opportunity.get('city')} — outside target markets"]


def role_relevance(title, matrix=None):
    matrix = matrix if matrix is not None else cfg_lib.load_search_matrix()
    roles = matrix.get("role_query_matrix") or {}
    t = (title or "").lower()
    for tier, score in (("core", 100.0), ("secondary", 80.0), ("adjacent", 60.0)):
        for role in roles.get(tier) or []:
            if role.lower() in t:
                return score, tier
    if any(word in t for word in ("bim", "revit", "architect", "design")):
        return 50.0, "related"
    return 25.0, "unrelated"


def portfolio_strength(opportunity):
    summary = opportunity.get("portfolio_evidence_summary")
    if not isinstance(summary, dict):
        return "INSUFFICIENT"
    direct = summary.get("direct_project_matches") or []
    if any(m.get("relevance") == "HIGH" for m in direct):
        return "STRONG"
    if direct:
        return "DIRECT"
    if summary.get("profile_capability_matches"):
        return "CAPABILITY"
    if summary.get("regional_matches"):
        return "REGIONAL"
    return "NONE"


def _compensation_dimension(requirements, expectations):
    salary = requirements.get("salary")
    benefits = requirements.get("benefits") or []
    bonus = min(16, 4 * len(benefits))
    if salary == UNKNOWN or not isinstance(salary, dict):
        evidence = ["Salary not disclosed"] + ([f"Benefits stated: {', '.join(benefits)}"] if benefits else [])
        return _clip(50 + bonus), evidence
    key = f"{salary.get('salary_currency')}_{salary.get('salary_period')}"
    top = salary.get("salary_max") or salary.get("salary_min")
    text = f"Salary stated: {salary.get('salary_min')}-{salary.get('salary_max')} {salary.get('salary_currency')}/{salary.get('salary_period')}"
    expected = (expectations or {}).get(key)
    if expected and top:
        ratio = float(top) / float(expected)
        score = 90 if ratio >= 1 else 70 if ratio >= 0.8 else 45
        return _clip(score + bonus), [text + f" vs your expectation {expected}"]
    return _clip(65 + bonus), [text + " (no salary expectation configured to compare)"]


def _difficulty_dimension(gap, requirements, candidate_years, candidate_certs):
    points, evidence = 20.0, []
    if gap["missing"]:
        points += min(36, 12 * len(gap["missing"]))
        evidence.append(f"{len(gap['missing'])} required skill(s) not in your profile")
    req = requirements.get("min_years_experience")
    if req is not None and req > candidate_years:
        points += min(32, 8 * (req - candidate_years))
        evidence.append(f"{req - candidate_years} year(s) short of the experience requirement")
    for barrier in requirements.get("eligibility_barriers") or []:
        points += 30
        evidence.append(barrier)
    for cert in requirements.get("certifications") or []:
        if cert.lower() not in candidate_certs:
            points += 8
            evidence.append(f"Asks for {cert}")
    if requirements.get("seniority") in ("MANAGER", "DIRECTOR") and candidate_years < 8:
        points += 10
    return _clip(points), evidence or ["No specific barriers found"]


def _confidence(opportunity, requirements):
    pts = 0
    if len(opportunity.get("description") or "") >= 200:
        pts += 20
    if requirements.get("required_skills"):
        pts += 15
    if requirements.get("min_years_experience") is not None:
        pts += 10
    if requirements.get("location") != UNKNOWN or opportunity.get("remote") is True:
        pts += 10
    if requirements.get("employment_type") not in (None, UNKNOWN):
        pts += 10
    if opportunity.get("date_posted"):
        pts += 10
    if opportunity.get("company"):
        pts += 10
    source_conf = opportunity.get("confidence_score")
    if source_conf is None or float(source_conf) >= 70:
        pts += 15
    return _clip(pts)


# --- the engine --------------------------------------------------------------------

def analyze(opportunity, profile=None, settings=None, model=None, company_lookup=None, contacts=None,
            expectations=None, now=None, explicit_sub_scores=None, llm_provider=None, requirements_override=None):
    """Full V1.4 analysis for one normalized opportunity. Pure: reads config,
    never writes. company_lookup(name) -> {"company_score", "grade", "is_target", ...} or None."""
    profile = cfg_lib.load_profile_skills() if profile is None else profile
    settings = settings or opportunity_priority.load_settings()
    model = model or scoring_model.active_model()
    taxonomy = load_taxonomy()
    candidate_years = int(profile.get("experience_years") or 0)
    expectations = expectations if expectations is not None else settings.get("salary_expectations") or {}

    requirements = requirements_override or extract_requirements(opportunity, taxonomy)
    gap = skills_gap(requirements, profile, taxonomy)
    if not opportunity.get("matched_modes"):
        opportunity_modes.apply_mode_classification(opportunity, precedence=settings["ranking"]["primary_mode_precedence"])

    dims, evidence = {}, {}
    dims["skills_match"], evidence["skills_match"] = _skills_dimension(gap, requirements, taxonomy=taxonomy)
    software_score, _ = _skills_dimension(gap, requirements, software_only=True, taxonomy=taxonomy)
    dims["experience_match"], evidence["experience_match"] = _experience_dimension(requirements, candidate_years)
    tiers = location_tiers()
    dims["location_match"], tier, evidence["location_match"] = _location_dimension(opportunity, requirements, tiers)
    mode_score = opportunity_priority.mode_priority_score(opportunity, settings)
    dims["employment_match"] = float(mode_score)
    evidence["employment_match"] = [f"Modes: {opportunity_priority.mode_label(opportunity)}; current goal "
                                    f"{settings.get('goal') or 'UNKNOWN'}"]

    company = company_lookup(opportunity.get("company")) if company_lookup else None
    if company and company.get("company_score") is not None:
        dims["company_quality"] = float(company["company_score"])
        evidence["company_quality"] = [f"Company grade {company.get('grade')} (score {company['company_score']})"]
    else:
        dims["company_quality"] = 50.0
        evidence["company_quality"] = ["No company intelligence yet — neutral"]

    role_score, role_tier = role_relevance(opportunity.get("job_title"))
    strength = portfolio_strength(opportunity)
    portfolio_score = _PORTFOLIO_SCORES[strength]

    job_level = requirements.get("seniority")
    cand_level = _profile_level(candidate_years)
    if job_level in SENIORITY_ORDER:
        step = SENIORITY_ORDER.index(job_level) - SENIORITY_ORDER.index(cand_level)
        growth = {-2: 25, -1: 40, 0: 70, 1: 88, 2: 70}.get(step, 50 if step > 2 else 20)
        growth_ev = [f"Role level {job_level.title()} vs your {cand_level.title()} level"]
    else:
        growth, growth_ev = 60, ["Role level not stated"]
    project_hits = [p for p in (profile.get("project_types") or [])
                    if p.lower() in (opportunity.get("description") or "").lower()
                    or p in (opportunity.get("project_types") or [])]
    if project_hits:
        growth += 10
        growth_ev.append("Project types you know: " + ", ".join(project_hits))
    if company and company.get("is_target"):
        growth += 5
    dims["career_growth"] = _clip(growth)
    evidence["career_growth"] = growth_ev

    dims["compensation"], evidence["compensation"] = _compensation_dimension(requirements, expectations)
    freshness = opportunity.get("freshness") or staleness.compute_freshness(opportunity, now=now)
    dims["freshness"] = float(_FRESHNESS_SCORES.get(freshness, 50))
    evidence["freshness"] = [f"Freshness {freshness}"]
    candidate_certs = {c.lower() for c in profile.get("certifications") or []}
    dims["application_difficulty"], evidence["application_difficulty"] = _difficulty_dimension(
        gap, requirements, candidate_years, candidate_certs)

    known_contacts = [c for c in (contacts or []) if (c.get("company") or "").strip().lower()
                      == (opportunity.get("company") or "").strip().lower()]
    net = 30 + (25 if company and company.get("is_target") else 0) + (15 if company and company.get("grade") in ("A+", "A") else 0)
    net += 20 if known_contacts else 0
    net += 10 if dims["skills_match"] >= 70 else 0
    dims["networking_value"] = _clip(net)
    evidence["networking_value"] = ([f"{len(known_contacts)} known contact(s) at this company"] if known_contacts else
                                    ["No contacts logged at this company yet"]) + (
        ["Target company"] if company and company.get("is_target") else [])

    dims["strategic_value"] = _clip(0.3 * role_score + 0.3 * portfolio_score + 0.2 * dims["location_match"]
                                    + 0.2 * dims["employment_match"])
    evidence["strategic_value"] = [f"Role relevance {role_tier}", f"Portfolio evidence {strength}"]

    w = model["profile_match_weights"]
    dims["profile_match"] = _clip((w["skills"] * dims["skills_match"] + w["experience"] * dims["experience_match"]
                                   + w["role_relevance"] * role_score + w["portfolio_evidence"] * portfolio_score) / 100)
    evidence["profile_match"] = [f"Skills {dims['skills_match']}, experience {dims['experience_match']}, "
                                 f"role {role_score:g} ({role_tier}), portfolio {strength}"]

    barriers = requirements.get("eligibility_barriers") or []
    eligibility = 2.0 if barriers else (8.0 if tier else 5.0)
    derived_sub_scores = {
        "technical": round(dims["skills_match"] / 10, 1), "experience": round(dims["experience_match"] / 10, 1),
        "software": round(software_score / 10, 1), "project": round(portfolio_score / 10, 1),
        "location": round(dims["location_match"] / 10, 1), "eligibility": eligibility,
        "career_value": round(dims["strategic_value"] / 10, 1), "compensation": round(dims["compensation"] / 10, 1),
    }
    if explicit_sub_scores is not None:
        explicit, sub_scores = True, {k: float(explicit_sub_scores[k]) for k in derived_sub_scores}
    elif (opportunity.get("scoring_result") or {}).get("sub_scores_explicit") is True:
        explicit = True
        sub_scores = {k: float(opportunity["scoring_result"].get(k)) for k in derived_sub_scores}
    else:
        explicit, sub_scores = False, derived_sub_scores
    mw = model["match_weights"]
    overall = _clip(sum(sub_scores[k] / 10 * mw[k] for k in mw))

    ow = model["opportunity_weights"]
    opportunity_score = _clip((ow["overall_match"] * overall + ow["company_quality"] * dims["company_quality"]
                               + ow["career_growth"] * dims["career_growth"] + ow["compensation"] * dims["compensation"]
                               + ow["freshness"] * dims["freshness"]
                               + ow["ease_of_application"] * (100 - dims["application_difficulty"])
                               + ow["networking_value"] * dims["networking_value"]
                               + ow["strategic_value"] * dims["strategic_value"]) / 100)
    confidence = _confidence(opportunity, requirements)

    decision, reasons, risks, recommendation = decide(
        opportunity, requirements, gap, dims, overall, opportunity_score, confidence, freshness, tier, company,
        strength, model, settings, cand_level)

    if llm_provider is not None and requirements_override is None:
        from scripts.intelligence import llm_enrichment
        enriched, info = llm_enrichment.enrich(opportunity, requirements, overall, provider=llm_provider)
        if info.get("used"):
            result = analyze(opportunity, profile, settings, model, company_lookup, contacts, expectations, now,
                             explicit_sub_scores, None, enriched)
            result["llm"] = info
            return result
        llm_info = info
    else:
        llm_info = {"used": False, "status": "NOT_REQUESTED"}

    return {
        "job_id": opportunity.get("id"), "company": opportunity.get("company"), "job_title": opportunity.get("job_title"),
        "model_version": model["version"], "analyzed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "requirements": requirements, "skills_gap": gap, "dimensions": dims, "evidence": evidence,
        "sub_scores": sub_scores, "sub_scores_source": "EXPLICIT" if explicit else "EVIDENCE_DERIVED",
        "overall_match": overall, "opportunity_score": opportunity_score, "confidence": confidence,
        "freshness": freshness, "portfolio_strength": strength, "role_tier": role_tier,
        "decision": decision, "decision_icon": DECISION_ICONS[decision], "legacy_decision": LEGACY_EQUIVALENT[decision],
        "reasons": reasons, "risks": risks, "recommendation": recommendation, "llm": llm_info,
    }


def decide(opportunity, requirements, gap, dims, overall, opportunity_score, confidence, freshness, tier, company,
           strength, model, settings, cand_level):
    t = model["decision_thresholds"]
    barriers = requirements.get("eligibility_barriers") or []
    reasons, risks = [f"{overall:g}% overall profile match (opportunity score {opportunity_score:g})"], []

    for skill in gap["matched"][:5]:
        reasons.append(f"{skill} explicitly required — in your profile")
    for t_skill in gap["transferable"]:
        risks.append(f"{t_skill['skill']} required — not demonstrated, transferable from {', '.join(t_skill['via'])}")
    for skill in gap["missing"]:
        risks.append(f"{skill} required — not in your profile")
    for skill in gap["preferred_missing"]:
        risks.append(f"{skill} (preferred) not demonstrated")
    req = requirements.get("min_years_experience")
    if req is not None and dims["experience_match"] >= 75:
        reasons.append(f"Experience fits: {req}+ years required")
    elif req is not None:
        risks.append(f"Experience gap: {req}+ years required")
    level = requirements.get("seniority")
    if level == cand_level:
        reasons.append(f"Seniority matches ({level.title()})")
    elif level in ("MANAGER", "DIRECTOR", "LEAD"):
        risks.append(f"{level.title()}-level role above your current level ({cand_level.title()})")
    if tier:
        reasons.append(f"{requirements.get('location')} matches target market tier {tier.get('tier')}")
    elif opportunity.get("remote") is True:
        reasons.append("Remote role")
    for b in barriers:
        risks.append(f"Eligibility: {b}")
    if company and company.get("grade") in ("A+", "A"):
        reasons.append(f"Company is a high-priority target (grade {company['grade']})")
    if strength in ("STRONG", "DIRECT"):
        matches = (opportunity.get("portfolio_evidence_summary") or {}).get("direct_project_matches") or []
        reasons.append("Direct portfolio evidence: " + ", ".join(m["project"] for m in matches))
    if settings.get("goal") and settings["goal"] in (opportunity.get("matched_modes") or []):
        reasons.append(f"Matches your current goal ({settings['goal']})")
    elif opportunity.get("matched_modes"):
        risks.append(f"Outside your current goal {settings.get('goal')} ({opportunity_priority.mode_label(opportunity)})")
    if freshness in ("FRESH", "RECENT"):
        reasons.append(f"Recently posted ({freshness})")
    elif freshness in ("AGING", "STALE"):
        risks.append(f"Posting is {freshness.lower()}")
    if requirements.get("salary") == UNKNOWN:
        risks.append("Salary not disclosed")
    if confidence < t["min_confidence_to_apply"]:
        risks.append(f"Low data confidence ({confidence:g}) — the posting is missing key information")

    difficulty = dims["application_difficulty"]
    if freshness == "CLOSED":
        decision = "SKIP"
        risks.insert(0, "Posting is closed (explicit evidence on the page)")
    elif barriers and overall < 60:
        decision = "SKIP"
    elif barriers:
        decision = "WATCH"
    elif (opportunity_score >= t["apply_now"]["opportunity"] and overall >= t["apply_now"]["overall_match"]
          and difficulty <= t["apply_now"]["max_difficulty"]):
        decision = "APPLY_NOW"
    elif opportunity_score >= t["apply"]["opportunity"] and overall >= t["apply"]["overall_match"]:
        decision = "APPLY"
    elif (overall >= t["network_first"]["overall_match"] and dims["networking_value"] >= t["network_first"]["min_networking_value"]
          and difficulty >= t["network_first"]["min_difficulty"]):
        decision = "NETWORK_FIRST"
    elif overall >= t["review"]["overall_match"]:
        decision = "REVIEW"
    elif overall >= t["watch"]["overall_match"]:
        decision = "WATCH"
    else:
        decision = "SKIP"

    if decision in ("APPLY_NOW", "APPLY") and confidence < t["min_confidence_to_apply"]:
        decision = "REVIEW"
        risks.insert(0, "Downgraded to REVIEW: not enough posting data to apply with confidence")

    # Phase 4.2 rule: work KNOWN to be outside the current goal is only pushed
    # when it clears the exceptional threshold (config/career_state.yaml).
    exceptional_min = (settings.get("exceptional") or {}).get("min_match_score")
    outside = opportunity_priority.is_outside_goal(opportunity, settings)
    if decision in ("APPLY_NOW", "APPLY") and outside and not (
            (settings.get("exceptional") or {}).get("enabled") and exceptional_min is not None and overall >= exceptional_min):
        decision = "REVIEW"
        risks.insert(0, f"Capped at REVIEW: outside your current goal ({settings.get('goal')}) and not exceptional")

    contact = "BIM manager" if "bim" in (opportunity.get("job_title") or "").lower() else "hiring manager"
    recommendation = {
        "APPLY_NOW": "Apply directly today: prepare the application packet and tailor the CV to the matched skills."
                     + (f" In parallel, reach the {contact}." if dims["networking_value"] >= 60 else ""),
        "APPLY": "Apply this week with a tailored CV and the most relevant portfolio project.",
        "NETWORK_FIRST": f"Network before applying: reach a {contact} or recruiter at {opportunity.get('company')} "
                         "to address the gaps, then apply.",
        "REVIEW": "Review manually before investing effort — check the risks below.",
        "WATCH": "Keep watching; do not invest application effort yet.",
        "SKIP": "Skip this opportunity.",
    }[decision]
    return decision, reasons, risks or ["No significant risks found"], recommendation


# --- persistence ---------------------------------------------------------------------

def _analysis_dir():
    return paths.DATA_DIR / "analyses"


def save_analysis(analysis, csv_path=None):
    """Appends a history row to tracking/analyses.csv and writes the full
    latest analysis to data/analyses/<job_id>.json."""
    csv_path = csv_path or paths.ANALYSES_CSV
    gap = analysis["skills_gap"]
    row = {
        "analysis_id": f"{analysis['job_id']}:{analysis['analyzed_at']}", "job_id": analysis["job_id"],
        "company": analysis["company"], "job_title": analysis["job_title"], "model_version": analysis["model_version"],
        "analyzed_at": analysis["analyzed_at"], "decision": analysis["decision"],
        "overall_match": analysis["overall_match"], "opportunity_score": analysis["opportunity_score"],
        "confidence": analysis["confidence"],
        **{k: analysis["dimensions"][k] for k in ("profile_match", "skills_match", "experience_match", "location_match",
                                                  "employment_match", "company_quality", "career_growth", "compensation",
                                                  "freshness", "application_difficulty", "networking_value",
                                                  "strategic_value")},
        "matched_skills": "|".join(gap["matched"]), "missing_skills": "|".join(gap["missing"]),
        "transferable_skills": "|".join(t["skill"] for t in gap["transferable"]),
        "reasons": "|".join(analysis["reasons"]), "risks": "|".join(analysis["risks"]),
        "recommendation": analysis["recommendation"], "llm_used": analysis["llm"].get("used", False),
    }
    storage.append_csv_rows(csv_path, ANALYSES_FIELDNAMES, [row])
    out_dir = _analysis_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{analysis['job_id']}.json").write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
    return row


def load_analysis(job_id):
    path = _analysis_dir() / f"{job_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def latest_analyses(csv_path=None):
    """{job_id: latest analysis row} from tracking/analyses.csv."""
    latest = {}
    for row in storage.read_csv(csv_path or paths.ANALYSES_CSV):
        latest[row["job_id"]] = row
    return latest
