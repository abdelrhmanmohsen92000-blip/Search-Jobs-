# Learning loop (V1.7)

The system learns from what actually happens to its recommendations — but it **never changes the
production model by itself**. Code: `scripts/intelligence/feedback.py`,
`scripts/intelligence/learning_loop.py`, `scripts/intelligence/scoring_model.py`.

## 1. Tell it what happened

```bash
python career_hunter.py feedback application JOB_ID
python career_hunter.py feedback interview   JOB_ID
python career_hunter.py feedback rejection   JOB_ID --reason="missing GCC experience"
python career_hunter.py feedback offer       JOB_ID
python career_hunter.py feedback no_response JOB_ID
python career_hunter.py feedback withdrawn   JOB_ID --reason="relocated"
python career_hunter.py feedback job         JOB_ID --rating bad --reason="not a BIM role"
```

(or the outcome buttons on the dashboard job page). Each entry goes to `tracking/feedback.csv`
together with what the system recommended at that moment: decision, opportunity score, overall
match, confidence, model version. Outcome kinds also move the application pipeline (actor
`human:feedback`); it only moves forward, except final outcomes.

## 2. Outcomes

`learning_loop.outcomes()` joins applications, the event log, feedback and the analysis that was
current when you applied:

| Outcome | Label |
|---|---|
| INTERVIEW, OFFER (ever reached) | positive |
| REJECTED, NO_RESPONSE (applied ≥ 30 days with no update, configurable) | negative |
| RATED_GOOD / RATED_BAD (job feedback without an application outcome) | positive / negative |
| PENDING (applied recently) | not counted yet |

## 3. Evaluate

```bash
python career_hunter.py learning evaluate
```

- **Fewer than 50 labelled outcomes** (`config/learning.yaml` `min_outcomes`): status
  `INSUFFICIENT_DATA` — rates by decision, outcome counts and top rejection reasons are shown,
  no weights are suggested.
- **Enough outcomes**: for each Opportunity-Score weight, compare its dimension between positive
  and negative outcomes (standardized difference). Weights move toward the evidence by
  `learning_rate`, capped at `max_relative_change` (30 %) per suggestion, ignoring effects
  below `min_effect`, then rescaled to sum to 100.
- **Back-test**: the proposed weights are applied to the same outcomes; the suggestion is only
  made if ranking quality (AUC: how often a positive outcome outranks a negative one) does not get
  worse.
- **Thresholds**: if APPLY_NOW converts worse than APPLY (with enough samples), it suggests
  raising the APPLY_NOW opportunity threshold.
- Rejection reasons are counted and mapped to likely dimensions (experience, skills, location,
  compensation) as hints.

A suggestion is written to `data/learning/suggestions/<id>.json` with status
`PENDING_APPROVAL`, the proposed version (e.g. 1.0 → 1.1), every change with its rationale, the
back-test, and whether synthetic outcomes were involved.

## 4. Approve (or not)

```bash
python career_hunter.py learning suggestions
python career_hunter.py learning approve S20261101090000            # adds model 1.1, keeps 1.0 active
python career_hunter.py learning approve S20261101090000 --activate # adds and activates 1.1
python career_hunter.py learning reject  S20261101090000 --reason "too few GCC outcomes"
python career_hunter.py reanalyze                                   # re-score stored jobs with the active version
python career_hunter.py config --model-version 1.0                  # roll back at any time
```

Approval creates a **new version** in `config/scoring_model.yaml` (`created_by: learning:<id>
approved by …`, `derived_from`, notes = rationale). Old versions are kept, so every stored
analysis stays explainable by the model that produced it. A suggestion computed against an older
active version must be re-evaluated first. Suggestions learned from SYNTHETIC demo outcomes are
refused for the real model; in a demo workspace they change only that workspace's own copy.

## 5. Simulation

`learning_loop.synthetic_records(n, driver=…)` generates clearly-marked synthetic outcomes in which
one dimension genuinely drives interviews. The test suite uses it to prove the loop finds the
planted signal, improves the back-test, and still changes nothing until approval.

## Still tracked from V1.4

`learning` (no sub-command) also prints the response / interview / offer rates by country, job
title, source and company, always with sample sizes, as before.
