"""Source-adapter registry.

Adding a new source: write a new module in this package implementing
SourceAdapter (see base.py), then register an instance here. Nothing else
in the pipeline (scripts/daily_research.py) needs to change — it only loops
over REGISTRY.
"""
from .base import SourceAdapter, SourceRunResult  # noqa: F401
from .company_careers import CompanyCareersAdapter
from .generic_search import GenericSearchAdapter
from .manual_import import ManualImportAdapter
from .remoteok import RemoteOKAdapter
from .remotive import RemotiveAdapter

REGISTRY = {
    "Remote OK": RemoteOKAdapter(),
    "Remotive": RemotiveAdapter(),
    "Manual Import": ManualImportAdapter(),
}

# Not registered for always-on daily runs (they need a per-query/per-company
# target, not a bare fetch()) but available to import directly:
#   GenericSearchAdapter, CompanyCareersAdapter
__all__ = ["REGISTRY", "SourceAdapter", "SourceRunResult", "GenericSearchAdapter", "CompanyCareersAdapter"]
