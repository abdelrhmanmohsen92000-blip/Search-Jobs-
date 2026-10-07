# AI decision engine (V1.4 → V1.7)

Deterministic by default, explainable always. Code: `scripts/intelligence/analysis_engine.py`,
`requirements_extractor.py`, `scoring_model.py`, `llm_enrichment.py`, `company_intel.py`.

## 1. Requirement extraction

From the posting (structured fields first, then text): responsibilities, required vs preferred
skills (section headings and wording such as "a plus" / "preferred"), software, minimum/maximum
years, education, certifications, languages, location, work mode, employment type, salary
(structured fields only), benefits, eligibility barriers (e.g. "must hold UK right to work"),
company, department, seniority, application method. Every field has a provenance tag
(`SOURCE_STRUCTURED`, `TEXT_EXTRACTED`, `DERIVED`, `AI_DERIVED`, `UNKNOWN`). Missing facts stay
`UNKNOWN`.

Skills are mapped to canonical names through `config/skills_taxonomy.yaml` (aliases such as
"Autodesk Revit" → Revit).

## 2. Skills gap

Compared with `config/profile_skills.yaml` (skills, software, verified capabilities):

- **MATCHED** — required and in your profile
- **TRANSFERABLE** — not in your profile, but the taxonomy lists a related skill you have
  (e.g. Dynamo via Revit) — shown as a risk, never claimed
- **MISSING** — required, no related skill
- preferred matched / preferred missing are tracked separately
- **Priority learning** (skills report): demand across active jobs × their opportunity scores

## 3. Dimensions (0–100)

| Dimension | Evidence |
|---|---|
| Profile match | weighted skills, experience, role relevance, portfolio evidence |
| Skills match | matched + 0.6 × transferable over all required (bonus for preferred matched) |
| Experience match | required years vs yours; manager/director levels capped below 8 years |
| Location match | target-market tier from `config/search_matrix.yaml` (Saudi Arabia P1 … Global/Remote P5) |
| Employment match | fit with your current goal and modes (`config/career_state.yaml`) |
| Company quality | company score (grade) from company intelligence; neutral 50 when unknown |
| Career growth | role level vs yours, project types you know, target company |
| Compensation | stated salary vs your expectations (if configured), stated benefits; 50 when undisclosed |
| Freshness | FRESH 100 … STALE 25, CLOSED 0 — from published dates only |
| Application difficulty | missing skills, experience gap, eligibility barriers, certifications (higher = harder) |
| Networking value | target company, grade, known contacts, skills fit |
| Strategic career value | role relevance, portfolio evidence, location, employment fit |

## 4. Scores

- **Overall Match** — the V1.1 100-point model over 8 sub-scores (technical, experience,
  software, project, location, eligibility, career value, compensation). Explicit sub-scores are
  used when a human assessed them; otherwise they are derived from the dimensions above
  (`sub_scores_source: EVIDENCE_DERIVED`).
- **Opportunity Score** — weighted mix of overall match, company quality, career growth,
  compensation, freshness, ease of application (100 − difficulty), networking value, strategic value.
- **Confidence** — how complete the posting data is (description length, stated skills, years,
  location, employment type, posting date, company, source confidence).

All weights and thresholds come from the **active version** of `config/scoring_model.yaml`; every
analysis stores the version that produced it.

## 5. Decisions

Evaluated in order:

1. Posting closed (explicit evidence) → 🔴 **SKIP**
2. Eligibility barrier → ⚪ **WATCH** (🔴 SKIP if overall match < 60)
3. Opportunity ≥ 82, match ≥ 78, difficulty ≤ 50 → 🔥 **APPLY_NOW**
4. Opportunity ≥ 68, match ≥ 64 → 🟢 **APPLY**
5. Match ≥ 55, networking value ≥ 60, difficulty ≥ 55 → 🔵 **NETWORK_FIRST**
6. Match ≥ 50 → 🟡 **REVIEW**
7. Match ≥ 35 → ⚪ **WATCH**, else 🔴 **SKIP**

Guards: APPLY/APPLY_NOW drop to REVIEW when confidence < 40 (not enough data), and when the job is
known to be outside your current goal (e.g. freelance while the goal is FULL_TIME) unless it
clears the exceptional threshold in `config/career_state.yaml`.

Every decision carries **reasons** (e.g. "Revit explicitly required — in your profile",
"Riyadh matches target market tier 1", "Direct portfolio evidence: …"), **risks** (e.g.
"Dynamo required — not demonstrated, transferable from Revit", "Salary not disclosed") and a
**recommendation**. `job JOB_ID` and the dashboard show all of them.

## 6. Company intelligence

Per company, from observed data only: job count, active opportunities, hiring trend (last 30 vs
previous 30 days), average match, target status/priority, region tier, known contacts, previous
applications. Score 0–100 → grade **A+ TARGET** (≥ 85), **A HIGH PRIORITY** (≥ 72), **B GOOD**
(≥ 58), **C NORMAL** (≥ 45), **D LOW PRIORITY**. `config/company_overrides.yaml` grades always
win. Size, industry and similar facts are `UNKNOWN` unless you logged them.

## 7. Networking and applications

For APPLY_NOW / APPLY / NETWORK_FIRST (and REVIEW ≥ 70): contact types by role family
(BIM manager, architecture director, recruiter, hiring manager, department lead, project manager,
employee/referral), priority, reason, outreach angle and a short draft that uses only stored facts.
Application packets add the CV and portfolio version, cover-letter rule (from the posting text),
skills to lead with / not to claim, project examples (from your portfolio evidence), application
URL (source only, else UNKNOWN), deadline (source only, else UNKNOWN) and the networking actions.

## 8. Optional LLM pass

With `provider: claude` in `config/ai.yaml` and `ANTHROPIC_API_KEY` set, jobs above the AI tier
get a second extraction pass. The model is asked to copy phrases exactly; each proposed item is
kept only if it appears in the posting (tagged `AI_DERIVED`), otherwise it is listed under
`rejected_unverifiable`. The model is never asked for salary, dates, URLs, company facts or job
status. Refusals, errors and invalid output fall back to the deterministic result and are recorded.

## AI safety rules (enforced in code and tests)

- Unknown stays UNKNOWN; nothing is invented (salary, requirements, company facts, status, URLs, dates).
- AI-derived data is always distinguishable (`AI_DERIVED`).
- The system never applies, sends emails or LinkedIn messages, or contacts anyone.
- Moving a job to APPLIED or later requires a human actor.
- Model weights change only through an approved, versioned suggestion.
