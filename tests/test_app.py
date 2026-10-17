"""Dashboard smoke tests with Flask's test client on cached fixtures."""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("flask")


@pytest.fixture
def client(data_fixture):
    from src.app.app import create_app
    return create_app().test_client()


def test_index_renders_all_panels(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for marker in ("Event", "Risk and decision", "Burn options", "Consequence if they collide",
                   "Probability vs harm", "Super-spreaders", "Operator brief", "WAIT"):
        assert marker in html
    assert "grounded" in html and "<svg" in html
    assert "historical CDM example" in html
    assert "creates new conjunction" in html and "along-track" in html


def test_footer_shows_platform(client):
    import platform
    html = client.get("/").get_data(as_text=True)
    assert platform.machine() in html and sys.byteorder in html


def test_index_without_cache_still_200(client):
    assert client.get("/?norad=99999").status_code == 200


def test_status_endpoint(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    d = r.get_json()
    assert d["running"] is False and d["platform"]["byteorder"] == sys.byteorder


def test_event_and_brief_endpoints(client):
    assert client.get("/api/event/25544").get_json()["event"]["primary"]["norad"] == 25544
    assert client.get("/api/event/1").status_code == 404
    b = client.get("/api/brief/25544").get_json()
    assert b["grounded"] is True and b["backend_used"] == "template"
    assert client.get("/api/brief/1").status_code == 404


def _write_globe_and_replay(data_fixture, facts):
    import json
    from src.consequence.snapshot import cloud_snapshots
    from test_snapshot import TLES, _facts
    from src.screen.catalog import parse_tle_text
    cloud_snapshots(_facts(facts), n_points=100, records=parse_tle_text(TLES, "active"))
    steps = [{"step": 1, "n_cdms": 1, "time_to_tca_days": 5.0, "latest_risk": -7.0, "predicted_risk": -7.0,
              "p_high": 0.01, "action": "MONITOR", "reasons": ["a"], "interval": [-8.0, -6.0]},
             {"step": 2, "final": True, "true_final_risk": -5.5, "true_high": True, "note": "x"}]
    out = data_fixture / "out"
    (out / "replay_7.json").write_text(json.dumps({"event_id": 7, "steps": steps}), encoding="utf-8")
    (out / "replay_demo.json").write_text(json.dumps(
        [{"event_id": 7, "role": "escalation", "title": "T", "summary": {"n_steps": 1, "final_action": "MONITOR"}}]),
        encoding="utf-8")


def test_globe_and_replay_endpoints(client, data_fixture, facts):
    _write_globe_and_replay(data_fixture, facts)
    g = client.get("/api/globe/25544")
    assert g.status_code == 200 and len(g.get_json()["snapshots"]) == 4
    svg = client.get("/api/globe/25544/fallback.svg")
    assert svg.status_code == 200 and b"<svg" in svg.data
    assert client.get("/api/replay/7").status_code == 200
    assert client.get("/api/replay/demo").get_json()[0]["event_id"] == 7
    assert client.get("/api/globe/1").status_code == 404
    html = client.get("/").get_data(as_text=True)
    assert "What if it collides? (3D)" in html and "Real-time decision replay" in html
    assert "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js" in html
