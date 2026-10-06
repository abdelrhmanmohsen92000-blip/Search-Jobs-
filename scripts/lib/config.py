"""Loaders for config/*.yaml."""
import functools

import yaml

from . import paths


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=None)
def load_search_matrix():
    return _load_yaml(paths.SEARCH_MATRIX)


@functools.lru_cache(maxsize=None)
def load_sources():
    return _load_yaml(paths.SOURCES)


@functools.lru_cache(maxsize=None)
def load_portfolio_projects():
    """config/portfolio_projects.yaml (real, verified project records) — a
    separate file from config/profile_skills.yaml so real portfolio data
    never has to be hand-merged into the example-laden profile file. Empty
    dict if the file doesn't exist (nothing to merge, no fabrication).
    """
    if not paths.PORTFOLIO_PROJECTS.exists():
        return {}
    return _load_yaml(paths.PORTFOLIO_PROJECTS)


@functools.lru_cache(maxsize=None)
def load_profile_skills():
    profile = _load_yaml(paths.PROFILE_SKILLS)
    extra = load_portfolio_projects()
    if extra.get("portfolio_projects"):
        profile = dict(profile)
        profile["portfolio_projects"] = list(profile.get("portfolio_projects") or []) + list(extra["portfolio_projects"])
    if extra.get("source"):
        profile["portfolio_source"] = extra["source"]
    return profile


@functools.lru_cache(maxsize=None)
def load_ai_config():
    return _load_yaml(paths.AI_CONFIG)


def all_job_titles(matrix=None):
    """Flatten job_families + discovered_titles into one list of titles."""
    matrix = matrix or load_search_matrix()
    titles = []
    for family_titles in matrix.get("job_families", {}).values():
        titles.extend(family_titles)
    for entry in matrix.get("discovered_titles", []) or []:
        titles.append(entry.split("#")[0].strip())
    # de-dupe, preserve order
    seen = set()
    unique = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def region_for_country(country, matrix=None):
    """Return the first matching region name for a country, or 'unclassified'."""
    if not country:
        return "unclassified"
    matrix = matrix or load_search_matrix()
    regions = matrix.get("regions", {})
    normalized = country.strip().lower()
    for region_name, countries in regions.items():
        for c in countries:
            if c.strip().lower() == normalized:
                return region_name
    return "unclassified"


def countries_for_region(region, matrix=None):
    matrix = matrix or load_search_matrix()
    return matrix.get("regions", {}).get(region, [])


DEFAULT_SEARCH_LIMITS = {
    "max_queries_per_run": 200,
    "max_results_per_query": 20,
    "max_pages": 3,
    "max_requests_per_source": 10,
}


def search_limits(matrix=None):
    """Phase 3 safety limits (config/search_matrix.yaml `search_limits`),
    merged over DEFAULT_SEARCH_LIMITS so a partially-specified or missing
    section never leaves a limit unset.
    """
    matrix = matrix or load_search_matrix()
    return {**DEFAULT_SEARCH_LIMITS, **(matrix.get("search_limits") or {})}
