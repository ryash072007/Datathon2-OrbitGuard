"""Live-catalogue, brief, audit and platform endpoints on the combined API (no network, no model)."""
from __future__ import annotations

import pytest

from orbitguard.api import create_app


class ML:
    def evidence(self):
        return {"status": "missing"}


class Physics:
    def evidence(self):
        return {"status": "missing"}


@pytest.fixture
def client(data_fixture, tmp_path):
    return create_app(tmp_path, ml_service=ML(), physics_service=Physics()).test_client()


def test_cached_live_analysis_and_grounded_template_brief(client):
    facts = client.get("/api/live/facts/25544").get_json()
    assert facts["event"]["threat"]["norad"] == 64962
    brief = client.get("/api/live/brief/25544").get_json()
    assert brief["backend_used"] == "template" and brief["grounded"] and "## Recommendation" in brief["text"]
    events = client.get("/api/live/events").get_json()
    assert events["events"][0]["norad"] == 25544 and len(events["survey"]) == 3


def test_missing_analysis_is_not_ready(client):
    assert client.get("/api/live/facts/99999").status_code == 503


def test_network_and_survey(client):
    net = client.get("/api/live/network").get_json()
    assert net["nodes"][0]["rank"] == 1 and net["summary"]["n_objects"] == 100
    assert client.get("/api/live/survey").get_json()["rows"][0]["norad"] == 25544


def test_operator_decisions_are_hash_chained(client):
    client.get("/api/live/brief/25544")  # a brief is logged too
    r = client.post("/api/audit/operator", json={"context": "live", "reference": "+T_0.5_3P", "choice": "accept",
                                                 "note": "executing after review"})
    assert r.status_code == 201
    audit = client.get("/api/audit").get_json()
    assert audit["intact"] and audit["head"]["kind"] == "operator" and audit["head"]["seq"] >= 1
    assert {r["kind"] for r in audit["recent"]} >= {"operator", "brief"}


@pytest.mark.parametrize("payload", [{"context": "live", "reference": "x", "choice": "launch"},
                                     {"context": "elsewhere", "reference": "x", "choice": "accept"},
                                     {"context": "live", "reference": "x" * 200, "choice": "defer"}])
def test_operator_input_is_validated(client, payload):
    assert client.post("/api/audit/operator", json=payload).status_code == 422


def test_analyse_validates_before_starting(client):
    assert client.post("/api/live/analyse", json={"norad": -1}).status_code == 422
    assert client.post("/api/live/analyse", json={"norad": 25544, "target_km": 0}).status_code == 422


def test_platform_reports_architecture(client):
    p = client.get("/api/platform").get_json()
    assert p["byteorder"] in {"little", "big"} and "sgp4_accelerated" in p
    ev = client.get("/api/evidence/platform").get_json()
    assert ev["network"]["summary"]["n_edges"] == 4 and ev["nnpa"] == {"status": "missing"}


def test_latency_recorder_is_rolling_and_reports_percentiles():
    from orbitguard.live import LatencyRecorder
    rec = LatencyRecorder(window=5)
    for ms in (1, 2, 3, 4, 5, 100):
        rec.record("forecast", ms)
    rec.record("forecast", None)
    rec.record("forecast", float("nan"))
    s = rec.summary()["forecast"]
    assert s["n"] == 5 and s["last_ms"] == 100 and s["p50_ms"] == 4 and s["p95_ms"] > 5


def test_latency_endpoint_reports_platform_and_forecast_stages(client):
    from orbitguard.live import record_forecast
    record_forecast({"elapsed_ms": 8.0, "stage_ms": {"decision": 3.0, "second_opinion": None}})
    body = client.get("/api/latency").get_json()
    assert body["stages"]["forecast"]["n"] >= 1 and "decision_layer" in body["stages"]
    assert {"machine", "hostname", "nnpa"} <= set(body["platform"])


def test_stage_timings_counts_burns_times_objects():
    from orbitguard.live import stage_timings
    facts = {"timings_s": {"find_approach_s": 1.0, "screen_s": 2.0, "consequence_s": 0.5},
             "burns": {"n_screened": 145, "n_objects_screened": 1000}}
    t = stage_timings(facts, 5.0, 0.1)
    assert t["burn_object_pairs"] == 145000 and t["pairs_per_s"] == 72500
    assert abs(sum(s["seconds"] for s in t["stages"]) - 5.0) < 1e-9
