#!/usr/bin/env python3
"""Search query generator.

Builds the concrete set of (title, employment_type, region/country, source)
combinations to search for a given cycle, from config/search_matrix.yaml and
config/sources.yaml. This module implements the SEARCH ENGINE — it does not
perform LIVE SEARCH EXECUTION (no network calls). See scripts/daily_research.py
and README.md "What requires browser/web access" for the distinction.
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import config as cfg_lib  # noqa: E402


def searchable_sources(sources=None, include_manual=False):
    sources = sources or cfg_lib.load_sources()
    out = []
    for bucket in ("job_boards", "freelance_sources"):
        for src in sources.get(bucket, []):
            if src.get("access_type") == "requires_manual_or_browser_access" and not include_manual:
                continue
            out.append({**src, "bucket": bucket})
    return out


def build_query_plan(region=None, remote_only=False, freelance_only=False, include_manual=True):
    """Returns a list of query dicts: {title, employment_type, region, source}.

    region: a key from config/search_matrix.yaml `regions` (e.g. "gulf"), or
            None for all regions plus worldwide_remote.
    remote_only: restrict employment_type to Remote and region to worldwide_remote.
    freelance_only: use freelance_keywords instead of job_families titles, and
            only freelance_sources.
    """
    matrix = cfg_lib.load_search_matrix()
    sources = cfg_lib.load_sources()

    if freelance_only:
        titles = matrix.get("freelance_keywords", [])
        employment_types = ["Freelance", "Contract", "Project-based"]
        src_list = [s for s in searchable_sources(sources, include_manual) if s["bucket"] == "freelance_sources"]
    else:
        titles = cfg_lib.all_job_titles(matrix)
        employment_types = matrix.get("employment_types", [])
        src_list = [s for s in searchable_sources(sources, include_manual) if s["bucket"] == "job_boards"]

    if remote_only:
        regions = ["worldwide_remote"]
        employment_types = ["Remote"]
    elif region:
        if region not in matrix.get("regions", {}):
            raise ValueError(f"Unknown region '{region}'. Known regions: {sorted(matrix.get('regions', {}))}")
        regions = [region]
    else:
        regions = list(matrix.get("regions", {}).keys())

    plan = []
    for title, employment_type, region_name, source in itertools.product(titles, employment_types, regions, src_list):
        plan.append(
            {
                "title": title,
                "employment_type": employment_type,
                "region": region_name,
                "countries": cfg_lib.countries_for_region(region_name, matrix),
                "source": source["name"],
                "source_access_type": source["access_type"],
                "query_string": f'"{title}" {employment_type} jobs {region_name.replace("_", " ")}',
            }
        )
    return plan


def summarize_plan(plan):
    by_access = {}
    for q in plan:
        by_access.setdefault(q["source_access_type"], 0)
        by_access[q["source_access_type"]] += 1
    return {
        "total_queries": len(plan),
        "by_source_access_type": by_access,
        "distinct_titles": len({q["title"] for q in plan}),
        "distinct_regions": len({q["region"] for q in plan}),
        "distinct_sources": len({q["source"] for q in plan}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=None, help="Region key from config/search_matrix.yaml")
    parser.add_argument("--remote", action="store_true", help="Worldwide remote only")
    parser.add_argument("--freelance", action="store_true", help="Freelance keywords/sources only")
    parser.add_argument("--no-manual", action="store_true", help="Exclude manual/browser-gated sources")
    parser.add_argument("--json", action="store_true", help="Print the full query plan as JSON")
    args = parser.parse_args()

    plan = build_query_plan(
        region=args.region, remote_only=args.remote, freelance_only=args.freelance, include_manual=not args.no_manual
    )

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(json.dumps(summarize_plan(plan), indent=2))


if __name__ == "__main__":
    main()
