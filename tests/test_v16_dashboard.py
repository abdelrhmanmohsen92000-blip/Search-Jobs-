"""V1.6 dashboard: JSON API (pure handler) and a real HTTP smoke test on localhost."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from scripts import demo
from scripts.dashboard import api, server
from scripts.intelligence import application_pipeline as ap, feedback


@pytest.fixture
def seeded(isolated_workspace):
    api.invalidate()
    demo.seed(isolated_workspace, with_activity=True)
    yield isolated_workspace
    api.invalidate()


SECTIONS = ("overview", "jobs", "opportunities", "companies", "applications", "networking", "interviews", "skills",
            "market", "sources", "settings", "notifications")


def test_every_section_endpoint_answers(seeded):
    for section in SECTIONS:
        status, payload = api.handle("GET", f"/api/{section}")
        assert status == 200, (section, payload)
    _, o = api.handle("GET", "/api/overview")
    assert o["synthetic_jobs"] == 11 and o["tiles"]["jobs"] == 11 and o["tiles"]["interviews"] == 1
    assert {d["decision"] for d in o["decisions"]} == {"APPLY_NOW", "APPLY", "NETWORK_FIRST", "REVIEW", "WATCH", "SKIP"}


def test_jobs_filters_sorting_and_facets(seeded):
    _, all_jobs = api.handle("GET", "/api/jobs")
    assert all_jobs["count"] == all_jobs["total"] == 11
    assert {"country", "city", "role_family", "company", "employment_type", "freshness", "status", "decision"} <= set(all_jobs["facets"])
    _, f = api.handle("GET", "/api/jobs", {"country": ["Saudi Arabia"], "min_score": ["70"]})
    assert f["jobs"] and all(j["country"] == "Saudi Arabia" and j["opportunity_score"] >= 70 for j in f["jobs"])
    _, f = api.handle("GET", "/api/jobs", {"sort": ["company"], "order": ["asc"]})
    assert [j["company"] for j in f["jobs"]] == sorted(j["company"] for j in f["jobs"])
    _, f = api.handle("GET", "/api/jobs", {"status": ["INTERVIEW"]})
    assert len(f["jobs"]) == 1
    _, f = api.handle("GET", "/api/jobs", {"remote": ["true"], "employment_type": ["Full"]})
    assert all(j["remote"] for j in f["jobs"])


def test_job_detail_has_analysis_packet_history_and_provenance(seeded):
    _, jobs = api.handle("GET", "/api/jobs")
    top = jobs["jobs"][0]
    status, d = api.handle("GET", f"/api/jobs/{top['id']}")
    assert status == 200
    assert d["analysis"]["decision"] == top["decision"] and len(d["analysis"]["dimensions"]) == 12
    assert d["packet"]["requires_human_approval"] is True and d["history"]
    assert d["provenance"]["field_sources"] and "networking" in d
    assert api.handle("GET", "/api/jobs/does-not-exist")[0] == 404


def test_kanban_move_updates_database(seeded):
    _, board = api.handle("GET", "/api/applications")
    assert board["columns"] == ["DISCOVERED", "SHORTLISTED", "READY", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED"]
    card = board["board"]["DISCOVERED"][0]
    status, moved = api.handle("POST", f"/api/applications/{card['job_id']}/move", body={"status": "READY", "note": "drag"})
    assert status == 200 and moved["application"]["status"] == "READY"
    assert ap.get_application(card["job_id"])["status"] == "READY"
    assert ap.history(card["job_id"])[-1]["actor"] == "human:dashboard"
    _, board = api.handle("GET", "/api/applications")
    assert card["job_id"] in [c["job_id"] for c in board["board"]["READY"]]
    rejected = board["board"]["REJECTED"][0]["job_id"]
    assert api.handle("POST", f"/api/applications/{rejected}/move", body={"status": "READY"})[0] == 409
    assert api.handle("POST", f"/api/applications/{rejected}/move", body={"status": "READY", "force": True})[0] == 200
    assert api.handle("POST", "/api/applications/nope/move", body={"status": "READY"})[0] == 404
    assert api.handle("POST", f"/api/applications/{card['job_id']}/move", body={})[0] == 400


def test_networking_feedback_and_notifications_writes(seeded):
    _, net = api.handle("GET", "/api/networking")
    action = net["open"][0]
    status, d = api.handle("POST", f"/api/networking/{action['action_id']}/status", body={"status": "DONE"})
    assert status == 200 and d["action"]["status"] == "DONE" and d["action"]["follow_up_date"]
    assert api.handle("POST", f"/api/networking/{action['action_id']}/status", body={"status": "SEND"})[0] == 400
    _, jobs = api.handle("GET", "/api/jobs")
    jid = jobs["jobs"][-1]["id"]
    status, d = api.handle("POST", "/api/feedback", body={"kind": "job", "job_id": jid, "rating": "bad", "reason": "not my field"})
    assert status == 200 and feedback.load_feedback()[-1]["actor"] == "human:dashboard"
    assert api.handle("POST", "/api/feedback", body={"kind": "nope", "job_id": jid})[0] == 400
    status, d = api.handle("POST", "/api/notifications/read", body={})
    assert status == 200 and d["marked"] >= 1


def test_settings_show_status_never_secret_values(seeded, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "super-secret-value")
    _, s = api.handle("GET", "/api/settings")
    assert s["environment"]["BRAVE_SEARCH_API_KEY"] == "set"
    assert "super-secret-value" not in json.dumps(s)
    assert s["model"]["active_version"] == "1.0" and s["learning"]["status"] == "INSUFFICIENT_DATA"
    assert len(s["schedules"]) == 7 and s["timezone"]


def test_unknown_routes_and_methods(seeded):
    assert api.handle("GET", "/api/nothing")[0] == 404
    assert api.handle("GET", "/not-api")[0] == 404
    assert api.handle("DELETE", "/api/jobs")[0] == 405


def test_http_server_smoke(seeded):
    srv = server.make_server(port=0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "Career Hunter" in html and "app.js" in html
        assert b"function hbar" in urllib.request.urlopen(base + "/app.js").read()
        data = json.loads(urllib.request.urlopen(base + "/api/overview").read())
        assert data["tiles"]["jobs"] == 11
        with pytest.raises(urllib.error.HTTPError) as e:  # writes need the dashboard's header
            urllib.request.urlopen(urllib.request.Request(base + "/api/notifications/read", data=b"{}", method="POST"))
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/notifications/read", data=b"{}", method="POST",
                                     headers={"X-Career-Hunter": "1", "Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["marked"] >= 0
        with pytest.raises(urllib.error.HTTPError) as e:  # no path traversal out of static/
            urllib.request.urlopen(base + "/..%2f..%2fapi.py")
        assert e.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()
