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
