"""Suite-wide isolation: every test runs against a throwaway workspace.

Mutable data (tracking/, data/, reports/) is redirected to a temporary
directory, so no test can ever write to the real trackers — even a test that
only patches some of the paths it touches. Tracker files are seeded with the
headers of the repository's real CSVs so readers see the normal schema.
Configuration (config/) is shared and read-only.
"""
import os

import pytest

from scripts.lib import paths


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path_factory):
    original = paths.WORKSPACE
    real_tracking = paths.ROOT / "tracking"
    workspace = tmp_path_factory.mktemp("workspace")
    (workspace / "tracking").mkdir()
    for f in real_tracking.glob("*.csv"):  # header only: tests never see the user's real rows
        with open(f, encoding="utf-8") as src:
            header = src.readline()
        (workspace / "tracking" / f.name).write_text(header, encoding="utf-8")
    os.environ.pop("CAREER_HUNTER_WORKSPACE", None)
    paths.use_workspace(workspace)
    try:
        yield workspace
    finally:
        paths.use_workspace(original)
