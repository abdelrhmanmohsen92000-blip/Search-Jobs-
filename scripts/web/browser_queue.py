"""Browser search queue.

For BROWSER_REQUIRED sources (LinkedIn, Glassdoor, Upwork) and PUBLIC_WEB
boards with no parser yet, the system never automates a search — instead it
generates a concrete, prioritized list of searches a human runs manually in
a logged-in browser, with instructions to export/copy results back into
data/raw/search_results/ for scripts/web/manual_search_import.py to pick up.
"""
import datetime as _dt
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib, paths  # noqa: E402
from scripts import search_config  # noqa: E402

# Real, publicly documented search-URL templates — a parameterized search
# page, never a fabricated job listing. None of these is a specific job; a
# human still reviews and copies real results from the page itself. Sources
# without a known template get url=None rather than a guessed one.
_SEARCH_URL_TEMPLATES = {
    "LinkedIn Jobs": "https://www.linkedin.com/jobs/search/?keywords={q}",
    "Glassdoor": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}",
    "Upwork": "https://www.upwork.com/nx/search/jobs/?q={q}",
    "Indeed": "https://www.indeed.com/jobs?q={q}",
    "Bayt": "https://www.bayt.com/en/international/jobs/?keyword={q}",
}

_TASK_TYPE_BY_SOURCE = {
    "LinkedIn Jobs": "OPEN_LINKEDIN_SEARCH",
    "Glassdoor": "OPEN_GLASSDOOR_SEARCH",
    "Upwork": "OPEN_UPWORK_SEARCH",
}


def _search_url(source_name, title, region_name):
    template = _SEARCH_URL_TEMPLATES.get(source_name)
    if not template:
        return None
    return template.format(q=urllib.parse.quote(f"{title} {region_name.replace('_', ' ')}"))


def _task_type(source_name, access_method):
    if access_method == "COMPANY_CAREERS":
        return "OPEN_COMPANY_CAREERS"
    return _TASK_TYPE_BY_SOURCE.get(source_name, "OPEN_BOARD_SEARCH")

HIGH_PRIORITY_TITLES = {
    "bim architect", "bim coordinator", "revit architect", "architectural bim specialist",
    "architectural bim coordinator", "technical architect",
}
MEDIUM_PRIORITY_TITLES = {
    "architect", "interior architect", "architectural designer",
}
# everything else (visualization, broad searches) is LOW priority


def _priority_for_title(title):
    t = title.lower()
    if t in HIGH_PRIORITY_TITLES:
        return "HIGH"
    if t in MEDIUM_PRIORITY_TITLES:
        return "MEDIUM"
    return "LOW"


def _expected_value(source_access_method, priority):
    if priority == "HIGH" and source_access_method == "BROWSER_REQUIRED":
        return "HIGH — flagship board, high-priority title"
    if priority == "HIGH":
        return "MEDIUM-HIGH"
    if priority == "MEDIUM":
        return "MEDIUM"
    return "LOW"


def _browser_required_sources():
    """BROWSER_REQUIRED sources regardless of their `enabled` flag in
    config/sources.yaml — disabled there only means "never auto-run them",
    not "leave them off the manual browser queue", since the queue is
    exactly where a human picks them up instead.
    """
    sources = cfg_lib.load_sources()
    out = []
    for bucket, items in sources.items():
        for src in items:
            if src.get("access_method") == "BROWSER_REQUIRED":
                out.append({**src, "bucket": bucket})
    return out


def build_browser_queue(region=None, remote_only=False, freelance_only=False, limit_per_source=5):
    """Returns a list of browser task dicts: {source, query, region, priority,
    expected_value, manual_action}. Covers both BROWSER_REQUIRED sources
    (LinkedIn, Glassdoor, Upwork — regardless of their `enabled` flag, since
    this queue is how a human covers them manually) and PUBLIC_WEB boards
    from the regular query plan, since those have no working parser yet either.
    """
    plan = search_config.build_query_plan(
        region=region, remote_only=remote_only, freelance_only=freelance_only, include_browser_required=False,
    )
    matrix = cfg_lib.load_search_matrix()
    titles = matrix.get("freelance_keywords", []) if freelance_only else cfg_lib.all_job_titles(matrix)
    regions = [region] if region and region.lower() not in search_config.GLOBAL_ALIASES else search_config.rank_regions(matrix)
    if remote_only:
        regions = ["worldwide_remote"]

    tasks = []
    seen_per_source = {}

    def add_task(source_name, access_method, title, region_name):
        seen_per_source.setdefault(source_name, 0)
        if seen_per_source[source_name] >= limit_per_source:
            return
        seen_per_source[source_name] += 1
        priority = _priority_for_title(title)
        manual_action = (
            "Run this query in a logged-in browser and export/copy results into "
            "data/raw/search_results/<source>.json (see README 'Manual search import')."
            if access_method == "BROWSER_REQUIRED" else
            "No working automated parser for this board yet — run manually and export results the same way, "
            "or contribute a parser (see README 'How to add a new source')."
        )
        query = f'"{title}" jobs {region_name.replace("_", " ")}'
        tasks.append({
            "task_type": _task_type(source_name, access_method),
            "source": source_name,
            "url": _search_url(source_name, title, region_name),
            "query": query,
            "region": region_name,
            "priority": priority,
            "reason": f"{priority}-priority title on a {access_method} source — no automated path exists for this source.",
            "expected_value": _expected_value(access_method, priority),
            "expected_information": "Job postings matching this query: title, company, location, posting date, and the "
                                     "job's own URL — export/copy them into data/raw/search_results/ in the SearchResult shape.",
            "manual_action": manual_action,
            "status": "PENDING",
            "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        })

    for src in _browser_required_sources():
        for title in titles:
            for region_name in regions:
                add_task(src["name"], "BROWSER_REQUIRED", title, region_name)

    for q in plan:
        if q["source_access_method"] != "PUBLIC_WEB":
            continue
        add_task(q["source"], "PUBLIC_WEB", q["title"], q["region"])

    # Phase 5: registry companies whose careers URL could not be verified. A
    # human finds and confirms the URL; nothing here proposes a guessed one.
    from scripts.sources import company_careers
    for target in company_careers.unverified_targets(company_careers.load_targets()):
        note = (target.get("url_verification") or {}).get("note", "")
        tasks.append({
            "task_type": "VERIFY_COMPANY_CAREER_URL",
            "source": target.get("company"),
            "url": None,
            "query": f'"{target.get("company")}" official careers page',
            "region": ", ".join(target.get("regions") or []) or "UNKNOWN",
            "priority": (target.get("priority") or "MEDIUM").upper(),
            "reason": f"Target company with no verified careers URL. {note}".strip(),
            "expected_value": "Unlocks automatic career-page monitoring for this company",
            "expected_information": "The company's official careers/job-listing URL on its own domain. Add it to "
                                    "config/target_companies.yaml with url_verification.status and enabled: true.",
            "manual_action": "Find the official careers page in a browser, confirm it lists jobs, then update "
                             "config/target_companies.yaml. Do not use an aggregator URL.",
            "status": "PENDING",
            "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        })

    priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    tasks.sort(key=lambda t: priority_rank.get(t["priority"], 3))
    return tasks


def generate_browser_queue_report(tasks, out_path=None):
    out_path = out_path or (paths.REPORTS_DIR / "browser_search_queue.md")
    today = _dt.date.today().isoformat()

    lines = [f"# Browser Search Queue — {today}", "",
             "These searches require a human-controlled, logged-in browser session — nothing here is automated. "
             "Run each query, then export/copy the results into `data/raw/search_results/<source>.json` "
             "(see README 'Manual search import') and run `python career_hunter.py web-import --directory "
             "data/raw/search_results/`.", ""]

    if not tasks:
        lines.append("_No browser tasks generated for this query — check region/filters._")

    for i, t in enumerate(tasks, 1):
        lines += [
            f"{i}. **[{t.get('task_type', 'OPEN_BOARD_SEARCH')}] Source:** {t['source']}",
            f"   **URL:** {t.get('url') or '(no direct search-URL template for this source — search it manually)'}",
            f"   **Query:** {t['query']}",
            f"   **Region:** {t['region']}",
            f"   **Priority:** {t['priority']}",
            f"   **Reason:** {t.get('reason', '')}",
            f"   **Expected value:** {t['expected_value']}",
            f"   **Expected information:** {t.get('expected_information', '')}",
            f"   **Manual instructions:** {t['manual_action']}",
            f"   **Status:** {t.get('status', 'PENDING')} (created {t.get('created_at', '')})",
            "",
        ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
