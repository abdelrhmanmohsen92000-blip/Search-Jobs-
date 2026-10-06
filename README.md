# AI Career Hunter — Abdelrhman Mohsen

A self-updating Global Career Opportunity System for BIM Architecture / Interior & Exterior Design job search, freelance discovery, company targeting, and professional networking.

This repo is the **data and process backbone**: profile source-of-truth, search matrices, scoring logic, and trackers. Actual searching (job boards, LinkedIn, company sites) is run manually or via an AI agent session that reads this repo, fills the trackers, and commits results back — keeping a durable, versioned record instead of a one-off chat answer.

## Structure

```
profile/
  profile.md              Source-of-truth professional profile (edit here, everything else reads from it)
docs/
  search-strategy.md       Countries, job title matrix, opportunity types, source list
  scoring-model.md          How the 0-100 opportunity score is computed
  decision-makers.md        How to classify and prioritize contacts (A/B/C)
templates/
  job-opportunity.md        Per-opportunity research template
  company-profile.md        Per-company research template
  contact-profile.md        Per-contact research template
  outreach-message.md       LinkedIn/email outreach drafting template
tracking/
  jobs.csv                 Master job opportunity tracker
  companies.csv             Master company discovery tracker
  contacts.csv               Master decision-maker / networking tracker
  applications.csv           Application + interview pipeline tracker
scripts/
  score_opportunity.py       Computes the weighted 0-100 score from a row of criteria
```

## Workflow

1. Keep `profile/profile.md` current — this is what every search and score is run against.
2. Add discovered jobs to `tracking/jobs.csv` using `templates/job-opportunity.md` as the research checklist; score with `scripts/score_opportunity.py`.
3. Add discovered companies to `tracking/companies.csv` using `templates/company-profile.md`, whether or not they have a public vacancy.
4. Add decision-makers to `tracking/contacts.csv`, categorized A/B/C per `docs/decision-makers.md`.
5. Track every application, conversation, and interview outcome in `tracking/applications.csv`.
6. Review outcomes periodically and refine `docs/search-strategy.md` (titles, countries, sources) based on what is actually converting — this is the "continuously improving" loop.

LinkedIn connection requests, messages, and any outreach are drafted using `templates/outreach-message.md` but always sent by a human (Abdelrhman) — never automated, per explicit instruction to keep sensitive/social actions under human approval.
