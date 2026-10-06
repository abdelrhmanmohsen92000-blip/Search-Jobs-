# Opportunity Scoring Model (0–100) — V1.1

Every opportunity gets one score so the pipeline can be ranked and triaged.
This is the current (V1.1) model, implemented in `scripts/lib/scoring.py`.
It supersedes the original 7-criterion model (the old `company_signal`
criterion is now split into `career_value` and `compensation`).

| Criterion | Weight | What to evaluate |
|---|---|---|
| Technical Match | 25 | Overlap between role requirements and BIM / Revit / Architecture / Interior / Exterior / Documentation / Coordination skills |
| Experience Match | 20 | Required years/seniority vs. 4+ years actual experience (penalize large over/under-ask) |
| Software Match | 15 | Required tools vs. Revit (expert), Navisworks, AutoCAD, BIM 360/ACC, 3ds Max |
| Project Match | 10 | Project types in the posting vs. residential/villas/commercial/healthcare/admin/landscape/large-scale experience |
| Location / Work Mode | 10 | Fit of remote/hybrid/on-site/relocation with stated openness to all modes |
| Eligibility | 10 | Visa sponsorship availability, work authorization, international-applicant friendliness |
| Career Value | 5 | Growth, seniority trajectory, brand/portfolio value of the company or project |
| Compensation Potential | 5 | Salary band (if known) and relocation-cost-adjusted value |

Each criterion is scored 0–10 (by the researcher or an agent reading the
posting), then weighted:

```
score = sum(sub_score_i / 10 * weight_i)   for i in the 8 criteria above
```

Use `scripts/lib/scoring.score_opportunity_record()` (or the CLI:
`python3 career_hunter.py score`) to compute this consistently, including
priority, recommendation, matched/missing skills, strengths, and risks.
`scripts/score_opportunity.py` remains as a thin CLI for just the numeric
score, now delegating to the same V1.1 weights.

## Priority bands
- **90–100 — EXCEPTIONAL**
- **75–89 — STRONG**
- **60–74 — GOOD**
- **40–59 — MODERATE**
- **0–39 — LOW**

A company with no public vacancy is never scored LOW by default — it is tagged
`HIDDEN_OPPORTUNITY` instead (see `scripts/company_intelligence.py`).

## Recommendation bands
- **≥85 — APPLY_NOW**
- **70–84 — APPLY**
- **50–69 — CONSIDER**
- **<50 — WATCH**
