"""Career-goal priority & exceptional opportunity engine (Phase 4.2).

Answers three different questions without conflating them:

    1. "What matches me?"            -> match_score (the unchanged 100-point score)
    2. "What matters for my goal?"   -> mode_priority_score / career_priority_score
    3. "Is anything exceptional?"    -> exceptional_opportunity / exceptional_reasons

match_score is never modified. career_priority_score scales it by how
relevant the opportunity's evidence-based modes are to the current goal in
config/career_state.yaml, with a configurable floor so mode can only pull a
score down by a bounded amount — a poor full-time match can never outrank a
strong freelance one just because FULL_TIME is the goal.

Exceptional status is evidence-only: every reason maps to a concrete field
(match_score, an explicitly assessed sub-score, direct portfolio project
evidence, explicit remote evidence). Reasons with no backing field in this
data model (prestigious company, major project, rare role, ...) are never
generated.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import career_state as career_state_lib  # noqa: E402
from scripts.lib.opportunity_modes import UNKNOWN, ensure_mode_defaults  # noqa: E402

# Fallbacks used only when config/career_state.yaml lacks a section; the
# shipped config sets every one of these explicitly. Exceptional detection
# is OFF unless configured — nothing is surfaced as exceptional by default.
FALLBACK_RANKING = {
    "primary_mode_precedence": ["REMOTE_FULL_TIME", "FULL_TIME", "FREELANCE", "PART_TIME", "CONTRACT"],
    "current_goal_score": 100,
    "mode_priority_scores": {"HIGH": 100, "MEDIUM": 70, "LOW": 40},
    "inactive_mode_score": 20,
    "unknown_mode_score": 50,
    "mode_weight_floor": 0.75,
    "career_priority_bands": {"HIGH": 75, "MEDIUM": 55},
    "outside_goal_max_label": "MEDIUM",
}
FALLBACK_EXCEPTIONAL = {"enabled": False}
FALLBACK_ALERTS = {"suppress_high_match_outside_goal": True}

LABEL_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

REASON_LABELS = {
    "exceptional_match": "Exceptional profile match",
    "unusually_high_career_value": "Unusually high career value",
    "unusually_high_compensation": "Unusually high compensation potential",
    "strong_portfolio_alignment": "Strong portfolio alignment (direct project evidence)",
    "exceptional_remote_opportunity": "Exceptional match that is explicitly remote",
}
# Reasons backed by evidence that is not stored in tracking/jobs.csv; when a
# record is reloaded from the CSV these are retained from the stored codes.
_RETAINED_EVIDENCE_REASONS = ("strong_portfolio_alignment",)


def load_settings(state=None):
    state = state if state is not None else career_state_lib.load_career_state()
    ranking = {**FALLBACK_RANKING, **(state.get("ranking") or {})}
    ranking["mode_priority_scores"] = {**FALLBACK_RANKING["mode_priority_scores"],
                                       **((state.get("ranking") or {}).get("mode_priority_scores") or {})}
    ranking["career_priority_bands"] = {**FALLBACK_RANKING["career_priority_bands"],
                                        **((state.get("ranking") or {}).get("career_priority_bands") or {})}
    return {
        "goal": state.get("current_primary_goal"),
        "modes": state.get("search_modes") or {},
        "ranking": ranking,
        "exceptional": {**FALLBACK_EXCEPTIONAL, **(state.get("exceptional") or {})},
        "alerts": {**FALLBACK_ALERTS, **(state.get("alerts") or {})},
    }


def _score_for_mode(mode, settings):
    ranking = settings["ranking"]
    if settings["goal"] and mode == settings["goal"]:
        return ranking["current_goal_score"]
    cfg = settings["modes"].get(mode) or {}
    if not cfg.get("enabled"):
        return ranking["inactive_mode_score"]
    return ranking["mode_priority_scores"].get((cfg.get("priority") or "LOW").upper(), ranking["inactive_mode_score"])


def mode_priority_score(opportunity, settings):
    matched = opportunity.get("matched_modes") or []
    if not matched:
        return settings["ranking"]["unknown_mode_score"]
    return max(_score_for_mode(m, settings) for m in matched)


def is_outside_goal(opportunity, settings):
    """True only when the job's modes are KNOWN and none is the current goal.
    UNKNOWN employment type is never treated as outside the goal."""
    matched = opportunity.get("matched_modes") or []
    return bool(settings["goal"] and matched and settings["goal"] not in matched)


def career_priority_score(match_score, mode_score, settings):
    if match_score is None:
        return None
    floor = float(settings["ranking"]["mode_weight_floor"])
    return round(float(match_score) * (floor + (1 - floor) * mode_score / 100.0), 1)


def career_priority_label(score, outside_goal, settings):
    if score is None:
        return "LOW"
    bands = settings["ranking"]["career_priority_bands"]
    label = "HIGH" if score >= bands["HIGH"] else "MEDIUM" if score >= bands["MEDIUM"] else "LOW"
    cap = settings["ranking"].get("outside_goal_max_label")
    if outside_goal and cap and LABEL_RANK[label] < LABEL_RANK.get(cap, 2):
        label = cap
    return label


def _direct_project_matches(opportunity):
    summary = opportunity.get("portfolio_evidence_summary")
    if isinstance(summary, dict):
        return summary.get("direct_project_matches") or []
    return []


def evaluate_exceptional(opportunity, settings):
    """Returns (is_exceptional, reason_codes, explanations). Triggers:
    exceptional_match, unusually_high_career_value. Supporting reasons are
    only attached to an opportunity that is already exceptional."""
    cfg = settings["exceptional"]
    if not cfg.get("enabled"):
        return False, [], []

    match = opportunity.get("match_score")
    sr = opportunity.get("scoring_result") or {}
    explicit = sr.get("sub_scores_explicit") is True
    codes, explanations = [], []

    def add(code, text):
        if code not in codes:
            codes.append(code)
            explanations.append(text)

    min_match = cfg.get("min_match_score")
    if match is not None and min_match is not None and match >= min_match:
        add("exceptional_match", f"{REASON_LABELS['exceptional_match']} (match {match:g} >= {min_match})")

    min_cv, cv_floor = cfg.get("min_career_value"), cfg.get("career_value_min_match_score")
    career_value = sr.get("career_value")
    if (explicit and min_cv is not None and cv_floor is not None and career_value is not None
            and match is not None and career_value >= min_cv and match >= cv_floor):
        add("unusually_high_career_value",
            f"{REASON_LABELS['unusually_high_career_value']} (career value {career_value:g}/10)")

    if not codes:
        return False, [], []

    compensation, min_comp = sr.get("compensation"), cfg.get("min_compensation")
    if explicit and compensation is not None and min_comp is not None and compensation >= min_comp:
        add("unusually_high_compensation",
            f"{REASON_LABELS['unusually_high_compensation']} (compensation {compensation:g}/10)")

    direct = [m for m in _direct_project_matches(opportunity) if m.get("relevance") == "HIGH"]
    if direct:
        add("strong_portfolio_alignment",
            f"{REASON_LABELS['strong_portfolio_alignment']}: {', '.join(m['project'] for m in direct)}")
    elif not isinstance(opportunity.get("portfolio_evidence_summary"), (dict, str)):
        for code in _RETAINED_EVIDENCE_REASONS:
            if code in (opportunity.get("exceptional_reasons") or []):
                add(code, REASON_LABELS[code])

    if "REMOTE_FULL_TIME" in (opportunity.get("matched_modes") or []):
        add("exceptional_remote_opportunity", REASON_LABELS["exceptional_remote_opportunity"])

    return True, codes, explanations


def evaluate_opportunity(opportunity, settings=None):
    """Sets the Phase 4.2 priority fields on one opportunity in place."""
    settings = settings or load_settings()
    ensure_mode_defaults(opportunity)
    mode_score = mode_priority_score(opportunity, settings)
    outside = is_outside_goal(opportunity, settings)
    cps = career_priority_score(opportunity.get("match_score"), mode_score, settings)
    exceptional, codes, explanations = evaluate_exceptional(opportunity, settings)

    opportunity["mode_priority_score"] = mode_score
    opportunity["career_priority_score"] = cps
    opportunity["career_priority"] = career_priority_label(cps, outside, settings)
    opportunity["outside_current_goal"] = outside
    opportunity["current_career_goal"] = settings["goal"]
    opportunity["exceptional_opportunity"] = exceptional
    opportunity["exceptional_reasons"] = codes
    opportunity["exceptional_explanations"] = explanations
    return opportunity


def rank_opportunities(opportunities, settings=None):
    """Deterministic views over already-evaluated opportunities:
        top_current - by career_priority_score (ties: match_score, then id)
        best_match  - highest match_score regardless of mode
        best_current- highest career_priority_score
        exceptional - every exceptional opportunity, by match_score,
                      including ones outside the current goal
    """
    settings = settings or load_settings()
    evaluated = [o if "career_priority_score" in o else evaluate_opportunity(o, settings) for o in opportunities]

    def current_key(o):
        return (-(o.get("career_priority_score") or 0), -(o.get("match_score") or 0), str(o.get("id") or ""))

    def match_key(o):
        return (-(o.get("match_score") or 0), str(o.get("id") or ""))

    top_current = sorted(evaluated, key=current_key)
    by_match = sorted(evaluated, key=match_key)
    return {
        "current_goal": settings["goal"],
        "top_current": top_current,
        "best_current": top_current[0] if top_current else None,
        "best_match": by_match[0] if by_match else None,
        "exceptional": [o for o in by_match if o.get("exceptional_opportunity")],
    }


def mode_label(opportunity):
    matched = opportunity.get("matched_modes") or []
    return " + ".join(matched) if matched else UNKNOWN
