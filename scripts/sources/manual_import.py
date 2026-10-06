"""Manual / human-in-the-loop import adapter.

Wraps data/raw/*.json ingestion (the mechanism V1.1's daily_research.py used
directly) as a proper source adapter, so manually- or browser-session-
collected batches go through the same SourceRunResult contract as the live
API adapters. This is also where LinkedIn, Glassdoor, and Upwork results
belong once a human has exported/copied them into a JSON batch — never via
automated scraping of those sites.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import paths  # noqa: E402
from scripts.sources.base import SourceAdapter, SourceRunResult  # noqa: E402


class ManualImportAdapter(SourceAdapter):
    name = "Manual Import"
    access_type = "MANUAL"

    def fetch(self, query=None, limit=None):
        if not paths.DATA_RAW.exists():
            return SourceRunResult(source=self.name, status="EMPTY", notes="data/raw/ does not exist yet.")

        records = []
        files_read = []
        for f in sorted(paths.DATA_RAW.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                return SourceRunResult(source=self.name, status="ERROR", error=f"{f.name}: {e}")
            batch = data if isinstance(data, list) else [data]
            records.extend(batch)
            files_read.append(f.name)

        if limit:
            records = records[:limit]

        if not records:
            return SourceRunResult(source=self.name, status="EMPTY", notes="No JSON batches found in data/raw/.")

        return SourceRunResult(
            source=self.name, status="SUCCESS", opportunities=records, raw_count=len(records),
            notes=f"Files read: {', '.join(files_read)}",
        )
