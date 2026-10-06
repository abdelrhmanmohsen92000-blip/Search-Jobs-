#!/usr/bin/env python3
"""Web Intelligence Layer orchestrator (V1.3).

    WEB SEARCH -> SEARCH RESULT COLLECTION -> RESULT EXTRACTION ->
    SOURCE IDENTIFICATION -> CONTENT EXTRACTION -> OPPORTUNITY EXTRACTION ->
    NORMALIZATION -> DEDUPLICATION -> SCORING -> COMPANY INTELLIGENCE ->
    NETWORKING -> APPLICATION INTELLIGENCE -> REPORT

Reuses the existing scoring/storage/reporting architecture from V1.1/V1.2
(scripts/lib/*, scripts/company_intelligence.py, scripts/daily_research.py's
normalize_and_score) rather than duplicating it. The only genuinely new
logic here is converting search results/pages into candidate opportunities
and routing COMPANY_SIGNAL classifications into company_intelligence.py.
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.daily_research import DEFAULT_SUB_SCORES, JOBS_FIELDNAMES, opportunity_to_jobs_row  # noqa: E402
from scripts.lib import config as cfg_lib, dedup as dedup_lib, entity_resolution, normalize as norm_lib  # noqa: E402
from scripts.lib import paths, scoring, staleness, storage  # noqa: E402
from scripts.company_intelligence import add_company  # noqa: E402
from scripts.web.manual_search_import import load_search_result_files, load_single_file  # noqa: E402
from scripts.web.opportunity_extractor import classify, extract_opportunity, _guess_company_from_signal_title  # noqa: E402

CLASSIFICATION_STATS_KEYS = ["OPEN_VACANCY", "FREELANCE_PROJECT", "COMPANY_SIGNAL", "IRRELEVANT"]


def process_search_results(search_results, page_results_by_url=None):
    """search_results: list of SearchResult (or dicts). page_results_by_url:
    optional {url: PageExtractionResult} for deeper extraction.

    Returns (candidates, rejected, classification_counts, hidden_opportunity_signals).
    `candidates` are normalized (not yet scored) opportunity dicts for
    OPEN_VACANCY / FREELANCE_PROJECT results. COMPANY_SIGNAL results are
    routed to hidden_opportunity_signals instead of becoming a job opportunity.
    """
    page_results_by_url = page_results_by_url or {}
    candidates, rejected = [], []
    classification_counts = {k: 0 for k in CLASSIFICATION_STATS_KEYS}
    hidden_opportunity_signals = []

    for sr in search_results:
        url = sr.url if hasattr(sr, "url") else sr.get("url")
        page_result = page_results_by_url.get(url)
        candidate, label = extract_opportunity(sr, page_result)
        classification_counts[label] = classification_counts.get(label, 0) + 1

        if label == "IRRELEVANT":
            continue

        if label == "COMPANY_SIGNAL":
            title = sr.title if hasattr(sr, "title") else sr.get("title")
            snippet = sr.snippet if hasattr(sr, "snippet") else sr.get("snippet")
            company_name = _guess_company_from_signal_title(title) or title or ""
            hidden_opportunity_signals.append({
                "company_name": company_name,
                "evidence_source": url or "search result",
                "bim_activity": snippet or "",
                "hiring_activity": "",
                "relevant_titles": "",
                "date_found": _dt.date.today().isoformat(),
            })
            continue

        candidate.pop("location_raw", None)
        normalized = norm_lib.normalize_opportunity(candidate)
        if not normalized.get("company") or not normalized.get("job_title"):
            rejected.append({**normalized, "rejection_reason": "missing company or job_title after extraction"})
            continue
        normalized["provenance"] = candidate.get("provenance")
        normalized["confidence_score"] = candidate.get("confidence_score")
        if label == "FREELANCE_PROJECT" and not normalized.get("employment_type"):
            normalized["employment_type"] = "Freelance"
        candidates.append(normalized)

    return candidates, rejected, classification_counts, hidden_opportunity_signals


def score_and_finalize(candidates, profile=None):
    """DEDUPLICATION (with source-preserving merge) -> SCORING -> lifecycle status."""
    merged, dropped_count = dedup_lib.merge_duplicates(candidates)

    company_names = [c.get("company") for c in merged if c.get("company")]
    company_map = entity_resolution.resolve_companies(company_names)

    scored = []
    for opp in merged:
        canonical = company_map.get(opp.get("company"))
        if canonical and canonical != opp.get("company"):
            opp["company_canonical"] = canonical

        sub_scores = opp.pop("_sub_scores", None) or DEFAULT_SUB_SCORES
        result = scoring.score_opportunity_record(opp, sub_scores, profile=profile)
        opp["match_score"] = result["score"]
        opp["priority"] = result["priority"]
        opp["reason"] = "; ".join(result["strengths"][:2]) or "Scored with neutral default sub-scores."
        opp["scoring_result"] = result
        opp["status"] = opp.get("status") or "scored"
        opp["lifecycle_status"] = staleness.compute_lifecycle_status(opp)
        scored.append(opp)

    scored.sort(key=lambda o: o.get("match_score") or 0, reverse=True)
    return scored, dropped_count


def save_to_jobs_csv(scored):
    if not scored:
        return
    storage.append_csv_rows(paths.JOBS_CSV, JOBS_FIELDNAMES, [opportunity_to_jobs_row(o) for o in scored])


def run_web_import(directory=None, file_path=None, dry_run=False):
    """CLI: web-import. LOAD -> VALIDATE -> NORMALIZE -> EXTRACT -> DEDUPLICATE
    -> SCORE -> SAVE -> REPORT, from a single file (--file) or a directory
    (--directory) of search-results JSON (default: data/raw/search_results/).
    """
    if file_path:
        search_results, load_errors = load_single_file(file_path)
        files_read = [str(file_path)] if not load_errors else []
    else:
        directory = directory or (paths.DATA_RAW / "search_results")
        search_results, files_read, load_errors = load_search_result_files(directory)

    if dry_run:
        return {
            "dry_run": True, "files_found": files_read, "search_results_loaded": len(search_results),
            "load_errors": load_errors,
        }

    profile = cfg_lib.load_profile_skills()
    candidates, rejected, classification_counts, hidden_signals = process_search_results(search_results)
    scored, dropped_count = score_and_finalize(candidates, profile=profile)

    save_to_jobs_csv(scored)
    if scored:
        storage.save_run_snapshot("processed", "web_import_opportunities", scored)

    companies_added = []
    for signal in hidden_signals:
        if not signal["company_name"]:
            continue
        rec = add_company(signal)
        companies_added.append(rec)

    stats = {
        "files_read": files_read,
        "load_errors": load_errors,
        "search_results_loaded": len(search_results),
        "classification_counts": classification_counts,
        "candidates_extracted": len(candidates),
        "rejected": len(rejected),
        "duplicates_merged": dropped_count,
        "opportunities_saved": len(scored),
        "hidden_opportunity_signals": len(hidden_signals),
        "companies_added_or_updated": len(companies_added),
    }

    return {"dry_run": False, "scored": scored, "rejected": rejected, "stats": stats, "companies_added": companies_added}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=None, help="A single search-results JSON file")
    parser.add_argument("--directory", default=None, help="A directory of search-results JSON files")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    directory = Path(args.directory) if args.directory else None
    result = run_web_import(directory=directory, file_path=args.file, dry_run=args.dry_run)
    print(json.dumps(result if result.get("dry_run") else result["stats"], indent=2, default=str))


if __name__ == "__main__":
    main()
