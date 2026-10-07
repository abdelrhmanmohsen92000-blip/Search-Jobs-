"""Versioned learning loop (V1.7).

    outcomes()      one record per job with a known result: what was RECOMMENDED
                    (decision, scores, dimensions, model version at the time) and
                    what HAPPENED (INTERVIEW / OFFER / REJECTED / NO_RESPONSE, or
                    your good/bad job rating), plus the reason you gave
    evaluate()      below `min_outcomes` (default 50): reports progress only.
                    Above it: compares dimensions between positive and negative
                    outcomes, back-tests a re-weighted Opportunity Score, and
                    writes a LEARNING SUGGESTION to data/learning/suggestions/
    approve(id)     YOUR explicit approval -> a NEW model version in
                    config/scoring_model.yaml (active only with activate=True)
    reject(id)      records that you declined it

Production weights are never changed silently: evaluate() only writes
suggestion files, and every approved change is a new, named, reversible model
version (`career_hunter.py config --model-version <v>` switches back).
"""
import datetime as _dt
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from scripts.lib import paths, storage  # noqa: E402

CONFIG_PATH = paths.CONFIG_DIR / "learning.yaml"
DIMENSIONS = ("overall_match", "company_quality", "career_growth", "compensation", "freshness", "ease_of_application",
              "networking_value", "strategic_value", "skills_match", "experience_match", "location_match")


def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _suggestions_dir():
    return paths.LEARNING_DIR / "suggestions"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --- outcomes -------------------------------------------------------------------------

def _analysis_snapshot(job_id, applied_on, history):
    """The analysis that was current when you applied (else the latest)."""
    rows = [r for r in history if r.get("job_id") == job_id]
    if not rows:
        from scripts.intelligence import analysis_engine
        a = analysis_engine.load_analysis(job_id)
        if not a:
            return None
        return {"decision": a["decision"], "overall_match": a["overall_match"], "opportunity_score": a["opportunity_score"],
                "confidence": a["confidence"], "model_version": a["model_version"], **a["dimensions"]}
    before = [r for r in rows if applied_on and (r.get("analyzed_at") or "")[:10] <= applied_on]
    return (before or rows)[-1]


def outcomes(today=None, config=None):
    from scripts.intelligence import application_pipeline as ap, feedback, insights
    config = config or load_config()
    today = today or _dt.date.today()
    applications = {a.get("opportunity_id"): a for a in ap.load_applications()}
    events = storage.read_csv(paths.APPLICATION_EVENTS_CSV)
    fb = feedback.load_feedback()
    history = storage.read_csv(paths.ANALYSES_CSV)
    jobs = {j["id"]: j for j in storage.read_csv(paths.JOBS_CSV) if j.get("id")}

    reached, reasons, ratings = {}, {}, {}
    for a in applications.values():
        reached.setdefault(a.get("opportunity_id"), set()).add(ap.normalize_status(a.get("status")))
    for e in events:
        reached.setdefault(e.get("job_id"), set()).add(ap.normalize_status(e.get("to_status")))
    for f in fb:
        if f.get("outcome") and f["outcome"] != "RATING":
            reached.setdefault(f["job_id"], set()).add(f["outcome"])
        if f.get("reason"):
            reasons.setdefault(f["job_id"], []).append(f["reason"])
        if f.get("kind") == "job":
            ratings[f["job_id"]] = f.get("rating")

    positive, negative = set(config.get("positive_outcomes") or []), set(config.get("negative_outcomes") or [])
    applied_like = {"APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED", "NO_RESPONSE"}
    records = []
    for job_id in sorted(set(reached) | set(ratings)):
        statuses = reached.get(job_id, set())
        app = applications.get(job_id) or {}
        applied_on = app.get("application_date") or ""
        if "OFFER" in statuses:
            outcome = "OFFER"
        elif "INTERVIEW" in statuses:
            outcome = "INTERVIEW"
        elif "REJECTED" in statuses:
            outcome = "REJECTED"
        elif "NO_RESPONSE" in statuses:
            outcome = "NO_RESPONSE"
        elif statuses & applied_like:
            stale = applied_on and (today - _dt.date.fromisoformat(applied_on[:10])).days >= int(
                config.get("no_response_after_days", 30))
            outcome = "NO_RESPONSE" if stale else "PENDING"
        elif job_id in ratings:
            outcome = "RATED_GOOD" if ratings[job_id] == "good" else "RATED_BAD"
        else:
            continue  # shortlisted/ready only: no outcome yet
        if outcome in positive or outcome == "RATED_GOOD":
            label = 1
        elif outcome in negative or outcome == "RATED_BAD":
            label = 0
        else:
            label = None
        snap = _analysis_snapshot(job_id, applied_on, history) or {}
        dims = {k: _num(snap.get(k)) for k in DIMENSIONS if k != "ease_of_application"}
        difficulty = _num(snap.get("application_difficulty"))
        dims["ease_of_application"] = None if difficulty is None else 100 - difficulty
        job = jobs.get(job_id) or app
        records.append({"job_id": job_id, "outcome": outcome, "label": label,
                        "source": "RATING" if outcome.startswith("RATED") else "APPLICATION",
                        "applied": bool(statuses & applied_like), "decision": snap.get("decision") or "UNKNOWN",
                        "recommended": snap.get("decision") in ("APPLY_NOW", "APPLY", "NETWORK_FIRST"),
                        "opportunity_score": _num(snap.get("opportunity_score")), "confidence": _num(snap.get("confidence")),
                        "model_version": snap.get("model_version") or "UNKNOWN", "reasons": reasons.get(job_id, []),
                        "synthetic": insights.is_synthetic(job), **dims})
    return records


# --- statistics -------------------------------------------------------------------------

def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _effect(pos, neg):
    """Standardized mean difference (Cohen's d). 0 when undefined."""
    if len(pos) < 2 or len(neg) < 2:
        return 0.0
    mp, mn = _mean(pos), _mean(neg)
    vp = sum((x - mp) ** 2 for x in pos) / (len(pos) - 1)
    vn = sum((x - mn) ** 2 for x in neg) / (len(neg) - 1)
    pooled = math.sqrt(((len(pos) - 1) * vp + (len(neg) - 1) * vn) / (len(pos) + len(neg) - 2))
    return 0.0 if pooled == 0 else (mp - mn) / pooled


def auc(scores_labels):
    """Probability a positive outcome scores higher than a negative one (ties = 0.5)."""
    pos = [s for s, y in scores_labels if y == 1]
    neg = [s for s, y in scores_labels if y == 0]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def opportunity_from_dims(record, weights, mapping):
    total = 0.0
    for key, w in weights.items():
        value = record.get(mapping.get(key, key))
        if value is None:
            return None
        total += w * value
    return total / 100


def _rescale(weights, target=100):
    """Integer weights summing to `target` (largest remainder)."""
    total = sum(weights.values()) or 1
    raw = {k: v * target / total for k, v in weights.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: target - sum(out.values())]:
        out[k] += 1
    return out


def _rates_by(records, key):
    groups = {}
    for r in records:
        if r["label"] is None:
            continue
        g = groups.setdefault(str(r.get(key)), {"n": 0, "positive": 0})
        g["n"] += 1
        g["positive"] += r["label"]
    for g in groups.values():
        g["rate"] = round(g["positive"] / g["n"] * 100, 1)
    return groups


def _reason_hints(records, config):
    counts = {}
    for r in records:
        for reason in r["reasons"]:
            counts[reason.strip()] = counts.get(reason.strip(), 0) + 1
    hints = {}
    for reason, n in counts.items():
        for dim, words in (config.get("reason_keywords") or {}).items():
            if any(w in reason.lower() for w in words):
                hints[dim] = hints.get(dim, 0) + n
    return sorted(counts.items(), key=lambda kv: -kv[1])[:10], hints


# --- evaluation & suggestions ----------------------------------------------------------

def _next_version(active, existing):
    major, _, minor = str(active).partition(".")
    n = int(minor or 0) + 1
    while f"{major}.{n}" in existing:
        n += 1
    return f"{major}.{n}"


def evaluate(records=None, config=None, model_path=None, save=True, today=None):
    from scripts.intelligence import scoring_model
    config = config or load_config()
    records = outcomes(today=today, config=config) if records is None else records
    labelled = [r for r in records if r["label"] is not None]
    model = scoring_model.active_model(model_path)
    min_outcomes = int(config.get("min_outcomes", 50))
    top_reasons, hints = _reason_hints(records, config)
    report = {
        "evaluated_at": _dt.datetime.now().isoformat(timespec="seconds"), "model_version": model["version"],
        "outcomes": len(labelled), "pending": sum(1 for r in records if r["label"] is None),
        "min_outcomes": min_outcomes, "by_outcome": {}, "by_decision": _rates_by(labelled, "decision"),
        "recommended_vs_not": _rates_by(labelled, "recommended"), "top_rejection_reasons": top_reasons,
        "reason_dimension_hints": hints, "includes_synthetic": any(r.get("synthetic") for r in labelled),
        "suggestion": None,
    }
    for r in records:
        report["by_outcome"][r["outcome"]] = report["by_outcome"].get(r["outcome"], 0) + 1
    if len(labelled) < min_outcomes:
        report["status"] = "INSUFFICIENT_DATA"
        report["message"] = (f"{len(labelled)}/{min_outcomes} outcomes recorded — keep logging feedback; "
                             "no weight changes are suggested before then.")
        return report

    pos = [r for r in labelled if r["label"] == 1]
    neg = [r for r in labelled if r["label"] == 0]
    if min(len(pos), len(neg)) < int(config.get("min_per_group", 5)):
        report["status"] = "INSUFFICIENT_CONTRAST"
        report["message"] = f"Need at least {config.get('min_per_group', 5)} positive and negative outcomes each."
        return report

    mapping = config.get("adjustable_weights") or {}
    weights = dict(model["opportunity_weights"])
    effects, proposed = {}, {}
    lr, cap, min_effect = float(config.get("learning_rate", 0.25)), float(config.get("max_relative_change", 0.3)), \
        float(config.get("min_effect", 0.15))
    for key, w in weights.items():
        dim = mapping.get(key)
        p = [r[dim] for r in pos if r.get(dim) is not None]
        n = [r[dim] for r in neg if r.get(dim) is not None]
        d = round(_effect(p, n), 3)
        effects[key] = {"dimension": dim, "effect": d, "mean_positive": round(_mean(p), 1) if p else None,
                        "mean_negative": round(_mean(n), 1) if n else None}
        change = 0.0 if abs(d) < min_effect else max(-cap, min(cap, lr * d))
        proposed[key] = max(0.0, w * (1 + change))
    proposed = _rescale(proposed)

    old_auc = auc([(opportunity_from_dims(r, weights, mapping), r["label"]) for r in labelled
                   if opportunity_from_dims(r, weights, mapping) is not None])
    new_auc = auc([(opportunity_from_dims(r, proposed, mapping), r["label"]) for r in labelled
                   if opportunity_from_dims(r, proposed, mapping) is not None])
    report.update(dimension_effects=effects, backtest={"auc_current": old_auc, "auc_proposed": new_auc})

    changes, rationale = {}, []
    if proposed != weights and new_auc is not None and old_auc is not None and new_auc >= old_auc:
        changes["opportunity_weights"] = proposed
        for key in proposed:
            if proposed[key] != weights[key]:
                e = effects[key]
                why = (f"positive outcomes average {e['mean_positive']} vs {e['mean_negative']} for negative; "
                       f"effect {e['effect']}") if abs(e["effect"]) >= min_effect else "rebalanced so weights sum to 100"
                rationale.append(f"{key}: {weights[key]} -> {proposed[key]} ({why})")
        rationale.append(f"Back-test on {len(labelled)} outcomes: ranking quality (AUC) {old_auc} -> {new_auc}")

    rates = report["by_decision"]
    t = model["decision_thresholds"]
    if all(rates.get(d, {}).get("n", 0) >= int(config.get("min_per_group", 5)) for d in ("APPLY_NOW", "APPLY")) \
            and rates["APPLY_NOW"]["rate"] < rates["APPLY"]["rate"]:
        changes["decision_thresholds"] = {"apply_now": {**t["apply_now"], "opportunity": t["apply_now"]["opportunity"] + 3}}
        rationale.append(f"APPLY_NOW converted worse than APPLY ({rates['APPLY_NOW']['rate']}% vs "
                         f"{rates['APPLY']['rate']}%): raise the APPLY_NOW opportunity threshold by 3")
    if not changes:
        report["status"] = "NO_CHANGE_SUGGESTED"
        report["message"] = "The current model already ranks your outcomes as well as the evidence-based alternative."
        return report

    all_versions = scoring_model.load_all(model_path).get("versions") or {}
    suggestion = {
        "suggestion_id": f"S{_dt.datetime.now():%Y%m%d%H%M%S}", "created_at": report["evaluated_at"],
        "status": "PENDING_APPROVAL", "base_version": model["version"],
        "proposed_version": _next_version(model["version"], all_versions), "changes": changes, "rationale": rationale,
        "outcomes_used": len(labelled), "includes_synthetic": report["includes_synthetic"],
        "backtest": report["backtest"], "top_rejection_reasons": top_reasons,
        "note": "Nothing has changed yet. Approve with `career_hunter.py learning approve <id> [--activate]`.",
    }
    if save:
        _suggestions_dir().mkdir(parents=True, exist_ok=True)
        (_suggestions_dir() / f"{suggestion['suggestion_id']}.json").write_text(json.dumps(suggestion, indent=2),
                                                                             encoding="utf-8")
    report["status"] = "SUGGESTION_CREATED"
    report["suggestion"] = suggestion
    return report


def load_suggestions():
    d = _suggestions_dir()
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []


def _save_suggestion(s):
    (_suggestions_dir() / f"{s['suggestion_id']}.json").write_text(json.dumps(s, indent=2), encoding="utf-8")


def _find(suggestion_id):
    s = next((s for s in load_suggestions() if s["suggestion_id"] == suggestion_id), None)
    if s is None:
        raise KeyError(f"No learning suggestion {suggestion_id!r}")
    return s


def approve(suggestion_id, approved_by="human:cli", activate=False, model_path=None, allow_synthetic=False):
    """The ONLY path from a suggestion to a production model change."""
    from scripts.intelligence import scoring_model
    s = _find(suggestion_id)
    if s["status"] != "PENDING_APPROVAL":
        raise ValueError(f"Suggestion {suggestion_id} is {s['status']}")
    target = Path(model_path) if model_path else scoring_model.default_path()
    if s.get("includes_synthetic") and target.resolve() == scoring_model.MODEL_PATH.resolve() and not allow_synthetic:
        raise ValueError("This suggestion was learned from SYNTHETIC demo outcomes; it will not be applied to the "
                         "real model (use the demo workspace, or --allow-synthetic if you really mean it)")
    if scoring_model.active_model(target)["version"] != s["base_version"]:
        raise ValueError(f"Suggestion was computed against model {s['base_version']} but "
                         f"{scoring_model.active_model(target)['version']} is active now — re-run `learning evaluate`")
    model = scoring_model.create_version(
        s["proposed_version"], s["changes"], notes="; ".join(s["rationale"]),
        created_by=f"learning:{suggestion_id} approved by {approved_by}", activate=activate, path=target)
    s.update(status="APPROVED", approved_at=_dt.datetime.now().isoformat(timespec="seconds"), approved_by=approved_by,
             activated=activate)
    _save_suggestion(s)
    return s, model


def reject(suggestion_id, reason="", rejected_by="human:cli"):
    s = _find(suggestion_id)
    if s["status"] != "PENDING_APPROVAL":
        raise ValueError(f"Suggestion {suggestion_id} is {s['status']}")
    s.update(status="REJECTED", rejected_at=_dt.datetime.now().isoformat(timespec="seconds"), rejected_by=rejected_by,
             reject_reason=reason)
    _save_suggestion(s)
    return s


# --- simulation (tests / acceptance only) ----------------------------------------------

def synthetic_records(n=60, seed=7, driver="strategic_value"):
    """SYNTHETIC outcomes where `driver` genuinely separates interviews from
    rejections — used to prove the loop finds a real signal. Marked synthetic."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        dims = {k: rng.uniform(30, 90) for k in DIMENSIONS}
        p = 1 / (1 + math.exp(-(dims[driver] - 60) / 6))
        label = 1 if rng.random() < p else 0
        out.append({"job_id": f"sim-{i}", "outcome": "INTERVIEW" if label else "REJECTED", "label": label,
                    "source": "APPLICATION", "applied": True, "decision": "APPLY", "recommended": True,
                    "opportunity_score": None, "confidence": 80, "model_version": "1.0",
                    "reasons": [] if label else ["missing GCC experience"], "synthetic": True, **dims})
    return out
