"""Windows-specific failure modes, reproduced on any OS."""
import os
import subprocess
import sys
import threading
import urllib.request
import zoneinfo

import pytest

from scripts import demo, scheduler
from scripts.dashboard import server
from scripts.lib import paths


def test_dashboard_script_type_ignores_a_bad_registry_mapping(monkeypatch):
    # Many Windows registries map .js to text/plain; with nosniff the browser would block the UI.
    monkeypatch.setattr(server.mimetypes, "guess_type", lambda *a, **k: ("text/plain", None))
    srv = server.make_server(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert urllib.request.urlopen(base + "/app.js").headers["Content-Type"].startswith("text/javascript")
        assert urllib.request.urlopen(base + "/app.css").headers["Content-Type"].startswith("text/css")
        assert urllib.request.urlopen(base + "/").headers["Content-Type"].startswith("text/html")
    finally:
        srv.shutdown()
        srv.server_close()


def test_missing_timezone_database_gives_an_actionable_error(monkeypatch):
    def missing(key):
        raise zoneinfo.ZoneInfoNotFoundError(key)
    monkeypatch.setattr(scheduler, "ZoneInfo", missing)
    with pytest.raises(ValueError, match="pip install tzdata"):
        scheduler.timezone()


def test_cli_does_not_crash_on_a_cp1252_console(isolated_workspace):
    demo.seed(isolated_workspace)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "NETWORK_MODE": "offline"}
    env.pop("PYTHONUTF8", None)
    result = subprocess.run([sys.executable, str(paths.ROOT / "career_hunter.py"), "--workspace",
                             str(isolated_workspace), "jobs"], capture_output=True, env=env, cwd=paths.ROOT,
                            timeout=120)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert "BIM Architect" in result.stdout.decode("utf-8")
