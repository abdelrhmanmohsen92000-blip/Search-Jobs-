#!/usr/bin/env python3
"""Search query generator.

Builds the concrete set of (title, employment_type, region/country, source)
combinations to search for a given cycle, from config/search_matrix.yaml and
config/sources.yaml. This module implements the SEARCH ENGINE — it does not
perform LIVE SEARCH EXECUTION on its own (see scripts/sources/ for the
adapters that do, and scripts/daily_research.py for the orchestration).

Regions are never hard-ranked "Gulf first" — rank_regions() derives a
priority order from logged outcomes in tracking/jobs.csv (average score,
volume) when data exists, falling back to a neutral/no-opinion order when it
doesn't.
"""
import argparse
import collections
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib, paths, storage  # noqa: E402

GLOBAL_ALIASES = {"global", "worldwide", "all"}


def searchable_sources(sources=None, bucket=None, include_browser_required=False, enabled_only=True, source_filter=None):
    sources = sources or cfg_lib.load_sources()
    buckets = [bucket] if bucket else ("job_boards", "freelance_sources")
    out = []
    for b in buckets:
        for src in sources.get(b, []):
            if enabled_only and src.get("enabled") is False:
                continue
            if src.get("access_method") == "BROWSER_REQUIRED" and not include_browser_required:
                continue
            if source_filter and src.get("name") != source_filter:
                continue
            out.append({**src, "bucket": b})
    return out


def all_sources_with_status(sources=None):
    """Every configured source (job_boards + freelance_sources + company_sources
    + professional_community_sources), regardless of enabled/access_method —
    used for SOURCE HEALTH reporting so disabled/browser-gated sources are
    still visible, not silently omitted.
    """
    sources = sources or cfg_lib.load_sources()
    out = []
    for bucket, items in sources.items():
        for src in items:
            out.append({**src, "bucket": bucket})
    return out


def rank_regions(matrix=None):
    """Rank region keys by evidence in tracking/jobs.csv (avg score desc,
    then volume desc). Regions with no logged data are appended in their
    config-declared order, un-ranked — never assumed worse, just unranked.
    """
    matrix = matrix or cfg_lib.load_search_matrix()
    all_regions = list(matrix.get("regions", {}).keys())

    jobs = storage.read_csv(paths.JOBS_CSV)
    region_scores = collections.defaultdict(list)
    for j in jobs:
        region = j.get("region")
        score = j.get("score")
        if region and score:
            try:
                region_scores[region].append(float(score))
            except ValueError:
                continue

    ranked_with_data = sorted(
        region_scores.keys(),
        key=lambda r: (sum(region_scores[r]) / len(region_scores[r]), len(region_scores[r])),
        reverse=True,
    )
    unranked = [r for r in all_regions if r not in region_scores]
    return ranked_with_data + unranked


def _resolve_regions(matrix, region, remote_only):
    if remote_only:
        return ["worldwide_remote"]
    if region is None:
        return rank_regions(matrix)
    if region.lower() in GLOBAL_ALIASES:
        return rank_regions(matrix)
    if region not in matrix.get("regions", {}):
        raise ValueError(f"Unknown region '{region}'. Known regions: {sorted(matrix.get('regions', {}))} "
                          f"(or 'global'/'worldwide'/'all')")
    return [region]


def build_query_plan(region=None, remote_only=False, freelance_only=False, include_browser_required=True,
                      source_filter=None, limit=None, employment_types=None):
    """Returns a list of query dicts: {title, employment_type, region, source}.

    region: a key from config/search_matrix.yaml `regions`, "global"/"worldwide"/"all"
            for every region ranked by rank_regions(), or None (same as global).
    remote_only: restrict employment_type to Remote and region to worldwide_remote.
    freelance_only: use freelance_keywords instead of job_families titles, and
            only freelance_sources.
    source_filter: restrict to a single source by exact name (--source).
    limit: cap the number of queries returned (--limit). Defaults to
            config/search_matrix.yaml `search_limits.max_queries_per_run`
            (Phase 3 safety limit) so an unbounded call (e.g. --region global
            with no --limit) can never silently explode into tens of
            thousands of queries. Pass limit=0 explicitly for truly unlimited.
    employment_types: Phase 4.1 Career Search Modes Engine override — a
            specific list of employment types (e.g. a career-state mode's own
            ["Contract"]) instead of the full matrix list. Ignored when
            remote_only is set (remote_only always wins, unchanged behavior).
    """
    matrix = cfg_lib.load_search_matrix()
    sources = cfg_lib.load_sources()

    if limit is None:
        limit = cfg_lib.search_limits(matrix)["max_queries_per_run"]
    elif limit == 0:
        limit = None

    if freelance_only:
        titles = matrix.get("freelance_keywords", [])
        resolved_employment_types = employment_types or ["Freelance", "Contract", "Project-based"]
        src_list = searchable_sources(sources, bucket="freelance_sources",
                                       include_browser_required=include_browser_required, source_filter=source_filter)
    else:
        titles = cfg_lib.all_job_titles(matrix)
        resolved_employment_types = employment_types or matrix.get("employment_types", [])
        src_list = searchable_sources(sources, bucket="job_boards",
                                       include_browser_required=include_browser_required, source_filter=source_filter)

    if remote_only:
        resolved_employment_types = ["Remote"]

    regions = _resolve_regions(matrix, region, remote_only)

    plan = [
        {
            "title": title,
            "employment_type": employment_type,
            "region": region_name,
            "countries": cfg_lib.countries_for_region(region_name, matrix),
            "source": source["name"],
            "source_access_method": source.get("access_method", "UNKNOWN"),
            "query_string": f'"{title}" {employment_type} jobs {region_name.replace("_", " ")}',
        }
        for title, employment_type, region_name, source in itertools.product(titles, resolved_employment_types, regions, src_list)
    ]

    if limit and len(plan) > limit:
        # Evenly-spaced sampling, not a linear prefix truncation: titles are
        # the outermost itertools.product dimension, so cutting the raw
        # sequence off at `limit` would silently keep only the first title
        # and drop every other one once (titles * employment_types * regions
        # * sources) exceeds `limit` — exactly backwards for "generate
        # multiple query variants, avoid query explosion" (Phase 3 §7).
        step = len(plan) / limit
        plan = [plan[int(i * step)] for i in range(limit)]
    return plan


ROLE_TIERS = ("core", "secondary", "adjacent")


def build_search_engine_queries(mode=None, limit=None, matrix=None):
    """Phase 5 discovery queries for a search-engine provider, e.g.
    '"BIM Architect" Riyadh', '"Revit Architect" remote', '"BIM Architect" Dubai freelance'.

    - Budget (limit, default search_limits.max_queries_per_run) is split across
      config `target_locations` tiers by weight, so a run never spends
      everything on one country; within each tier, core roles come first and
      locations rotate so they are not all spent on one city.
    - mode (an entry from scripts.lib.career_state.active_modes()) adds its own
      `query_terms` (one per query, rotating) and, with remote_only_locations,
      searches "remote" instead of the target locations.
    - One role per query; skills are never ANDed together.
    """
    matrix = matrix if matrix is not None else cfg_lib.load_search_matrix()
    limit = limit if limit is not None else cfg_lib.search_limits(matrix)["max_queries_per_run"]
    roles = [(tier, r) for tier in ROLE_TIERS for r in (matrix.get("role_query_matrix") or {}).get(tier) or []]
    tiers = matrix.get("target_locations") or []
    if not roles or not tiers or not limit:
        return []
    mode = mode or {}
    terms = mode.get("query_terms") or [None]
    if mode.get("remote_only_locations"):
        tiers = [{"tier": 5, "region": "REMOTE", "locations": ["remote"], "weight": 1}]

    total_weight = sum(t.get("weight", 1) for t in tiers) or 1
    queries, seen, term_i = [], set(), 0
    for t in sorted(tiers, key=lambda t: t.get("tier", 99)):
        share = max(1, round(limit * t.get("weight", 1) / total_weight))
        locations = t.get("locations") or []
        taken = 0
        for i, (role_tier, role) in enumerate(roles):
            if taken >= share or len(queries) >= limit:
                break
            location = locations[i % len(locations)] if locations else ""
            term = terms[term_i % len(terms)]
            term_i += 1
            query = " ".join(x for x in (f'"{role}"', location, term) if x)
            if query in seen:
                continue
            seen.add(query)
            queries.append({"query_string": query, "role": role, "role_tier": role_tier, "location": location,
                            "region": t.get("region"), "region_tier": t.get("tier"), "mode": mode.get("name")})
            taken += 1
    return queries[:limit]


def summarize_plan(plan, matrix=None):
    by_access = {}
    for q in plan:
        by_access.setdefault(q["source_access_method"], 0)
        by_access[q["source_access_method"]] += 1
    return {
        "total_queries": len(plan),
        "by_source_access_method": by_access,
        "distinct_titles": len({q["title"] for q in plan}),
        "distinct_regions": len({q["region"] for q in plan}),
        "distinct_sources": len({q["source"] for q in plan}),
        "region_rank_order": rank_regions(matrix),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=None, help="Region key, or 'global'/'worldwide'/'all'")
    parser.add_argument("--remote", action="store_true", help="Worldwide remote only")
    parser.add_argument("--freelance", action="store_true", help="Freelance keywords/sources only")
    parser.add_argument("--source", default=None, help="Restrict to a single source by name")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of queries generated")
    parser.add_argument("--no-browser-required", action="store_true", help="Exclude BROWSER_REQUIRED sources")
    parser.add_argument("--json", action="store_true", help="Print the full query plan as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Show plan summary + coverage, touch no files")
    args = parser.parse_args()

    plan = build_query_plan(
        region=args.region, remote_only=args.remote, freelance_only=args.freelance,
        include_browser_required=not args.no_browser_required, source_filter=args.source, limit=args.limit,
    )

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(json.dumps(summarize_plan(plan), indent=2))


if __name__ == "__main__":
    main()
