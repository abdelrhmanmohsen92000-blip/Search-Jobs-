# Opportunity Scoring Model (0–100)

Every opportunity gets one score so the pipeline can be ranked and triaged.

| Criterion | Weight | What to evaluate |
|---|---|---|
| Technical Match | 25% | Overlap between role requirements and BIM / Revit / Architecture / Interior / Exterior / Documentation / Coordination skills |
| Experience Match | 20% | Required years/seniority vs. 4+ years actual experience (penalize large over/under-ask) |
| Software Match | 15% | Required tools vs. Revit (expert), Navisworks, AutoCAD, BIM 360/ACC, 3ds Max |
| Project Match | 10% | Project types in the posting vs. residential/villas/commercial/healthcare/admin/landscape/large-scale experience |
| Location / Work Mode | 10% | Fit of remote/hybrid/on-site/relocation with stated openness to all modes |
| Eligibility | 10% | Visa sponsorship availability, work authorization, international-applicant friendliness |
| *(remaining 10%)* | 10% | Reserved: company quality / growth signal / compensation signal — score subjectively 0–10 based on available evidence |

Each criterion is scored 0–10 by the researcher, then weighted:

```
score = (technical*0.25 + experience*0.20 + software*0.15 + project*0.10
         + location*0.10 + eligibility*0.10 + company_signal*0.10) * 10
```

Use `scripts/score_opportunity.py` to compute this from the 7 sub-scores so it's never done by hand inconsistently.

## Score bands (for triage)
- **80–100** — Apply immediately, customize application fully.
- **60–79** — Apply with a tailored application; medium priority.
- **40–59** — Apply opportunistically / keep in backlog.
- **<40** — Log for market awareness only; do not prioritize.
