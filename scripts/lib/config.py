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
def load_profile_skills():
    return _load_yaml(paths.PROFILE_SKILLS)


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
