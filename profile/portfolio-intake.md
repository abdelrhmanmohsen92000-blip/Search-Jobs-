# Portfolio Intake — fill this in with real project data

> **This file contains no fabricated project data.** The repository was audited (Phase 2,
> `docs/PRODUCTION_READINESS.md`) for any existing CV, resume, or portfolio file — none exists.
> `profile/profile.md` and `config/profile_skills.yaml` only record employers and broad
> *project-exposure categories* (e.g. "Residential, luxury villas, commercial, healthcare,
> administrative, landscape/parks, large-scale developments"), not individually named projects
> with specific details (name, location, area, dates, exact responsibilities per project).
>
> This file seeds one stub entry per **real, verified employer** already in `profile/profile.md`
> — every field beyond the employer name is `UNKNOWN`/empty on purpose, never guessed. Fill in
> real project names and details to activate portfolio intelligence
> (`scripts/intelligence/application_strategy.py:match_portfolio_projects`); until then it
> correctly reports `PORTFOLIO_DATA_INSUFFICIENT`.
>
> Schema: `schemas/portfolio_project.schema.json`. Worked example (placeholder values, not real):
> `config/portfolio_projects.example.yaml`.
>
> **When you add a real entry:** copy its structure into `config/profile_skills.yaml` under a new
> top-level `portfolio_projects:` key (see the example file for the exact YAML shape). Do not
> leave real data only in this Markdown file — the code reads `profile_skills.yaml`.

## Known real employers (from profile/profile.md) — one stub per employer

### EDEC
- name: UNKNOWN (add the real project name)
- project_types: UNKNOWN
- location: UNKNOWN
- area_sqm: UNKNOWN
- role: UNKNOWN
- responsibilities: UNKNOWN
- software: UNKNOWN (likely overlaps with config/profile_skills.yaml's software list, but only
  list what was actually used on this specific project)
- bim_level: UNKNOWN
- disciplines: UNKNOWN
- deliverables: UNKNOWN
- scope: UNKNOWN
- status: UNKNOWN
- achievements: UNKNOWN

### Al-ORABI Engineering Consulting
- name: UNKNOWN
- project_types: UNKNOWN
- location: UNKNOWN
- area_sqm: UNKNOWN
- role: UNKNOWN
- responsibilities: UNKNOWN
- software: UNKNOWN
- bim_level: UNKNOWN
- disciplines: UNKNOWN
- deliverables: UNKNOWN
- scope: UNKNOWN
- status: UNKNOWN
- achievements: UNKNOWN

### VISION INTERNATIONAL GROUP
- name: UNKNOWN
- project_types: UNKNOWN
- location: UNKNOWN
- area_sqm: UNKNOWN
- role: UNKNOWN
- responsibilities: UNKNOWN
- software: UNKNOWN
- bim_level: UNKNOWN
- disciplines: UNKNOWN
- deliverables: UNKNOWN
- scope: UNKNOWN
- status: UNKNOWN
- achievements: UNKNOWN

### DIZ Studio
- name: UNKNOWN
- project_types: UNKNOWN
- location: UNKNOWN
- area_sqm: UNKNOWN
- role: UNKNOWN
- responsibilities: UNKNOWN
- software: UNKNOWN
- bim_level: UNKNOWN
- disciplines: UNKNOWN
- deliverables: UNKNOWN
- scope: UNKNOWN
- status: UNKNOWN
- achievements: UNKNOWN

### Freelance architectural work
- name: UNKNOWN
- project_types: UNKNOWN
- location: UNKNOWN
- area_sqm: UNKNOWN
- role: UNKNOWN
- responsibilities: UNKNOWN
- software: UNKNOWN
- bim_level: UNKNOWN
- disciplines: UNKNOWN
- deliverables: UNKNOWN
- scope: UNKNOWN
- status: UNKNOWN
- achievements: UNKNOWN

---

A single employer may have produced multiple distinct projects — duplicate a section as needed.
Each real project entry you add moves `portfolio_recommendation()` and
`match_portfolio_projects()` from `PORTFOLIO_DATA_INSUFFICIENT` to a real, evidence-backed match.
