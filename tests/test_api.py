"""HTTP/job boundary tests, independent of scientific model correctness."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import pytest

from orbitguard.api import create_app, JobStore


class ML:
    def evidence(self):
        return {"ready": False, "status": "not_trained"}

    def list_events(self, limit=100):
        return [{"event_id": "test:1", "latest_log10_pc": -5.0}][:limit]

    def overview(self):
        return {"count": 1, "columns": {"event_id": ["test:1"], "risk": [-5.0], "c_object_type": ["DEBRIS"]}}

    def get_event(self, event_id):
        if event_id != "test:1":
            raise KeyError(event_id)
        return {"event_id": event_id, "history": [{"event_id": event_id, "risk": -5, "time_to_tca": 2}]}

    def forecast(self, history):
        if any(row.get("time_to_tca", 0) < 2 for row in history):
            raise ValueError("Records inside 48 hours are not eligible inputs")
        return {"forecast_log10_pc": -5.0, "warnings": ["Test service"]}


class Physics:
    def list_scenarios(self):
        return [{"scenario_id": "case", "source": "synthetic"}]

    def get_scenario(self, scenario_id):
        if scenario_id != "case":
            raise KeyError(scenario_id)
        return {"scenario_id": "case", "source": "synthetic"}

    def evidence(self):
        return {"status": "not_run"}


def complete_worker(root, scenario_id, overrides):
    return {"scenario_id": scenario_id, "source": "synthetic", "recommendation": None}


@pytest.fixture
def client(tmp_path):
    with ThreadPoolExecutor(max_workers=1) as executor:
        app = create_app(tmp_path, ml_service=ML(), physics_service=Physics(),
                         job_executor=executor, screen_worker=complete_worker)
        app.config["TESTING"] = True
        yield app.test_client()


def test_forecast_boundary_and_json_errors(client):
    assert client.post("/api/forecast", json={"history": []}).status_code == 422
    assert client.post("/api/forecast", json={"history": ["invalid"]}).status_code == 422
    response = client.post("/api/forecast", json={"history": [{"risk": -5, "time_to_tca": 1}]})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "invalid_input"
    assert client.post("/api/forecast", data="invalid", content_type="application/json").status_code == 400
    assert client.get("/api/events?limit=-1").status_code == 422
    assert client.get("/api/events?limit=nan").status_code == 422


def test_job_lifecycle_download_and_persistence(client):
    submitted = client.post("/api/screen", json={"scenario_id": "case"})
    assert submitted.status_code == 202
    job_id = submitted.json["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}")
        if job.json["status"] == "completed":
            break
        time.sleep(.005)
    assert job.json["status"] == "completed"
    assert job.json["result"]["source"] == "synthetic"
    download = client.get(f"/api/runs/{job_id}")
    assert download.status_code == 200
    assert "attachment" in download.headers["Content-Disposition"]
    assert json.loads(download.data)["result"]["recommendation"] is None


def test_unknown_routes_and_missing_evidence(client):
    assert client.get("/api/jobs/not-a-uuid").status_code == 404
    assert client.get("/api/scenarios/missing").status_code == 404
    assert client.post("/api/screen", json={"scenario_id": "missing"}).status_code == 404
    assert client.get("/api/unknown").status_code == 404
    assert client.get("/api/evidence").json["runtime"]["status"] == "not_run"
    assert client.get("/api/health").json["model"]["ready"] is False


def test_queue_has_backpressure(tmp_path):
    release = threading.Event()
    def blocked(*args):
        release.wait(2)
        return {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        jobs = JobStore(tmp_path, executor, blocked, max_pending=1)
        jobs.submit("case", {})
        try:
            with pytest.raises(OverflowError):
                jobs.submit("case", {})
        finally:
            release.set()


def test_failed_job_remains_explicit(tmp_path):
    def fail(*args):
        raise ValueError("Unsupported covariance")
    with ThreadPoolExecutor(max_workers=1) as executor:
        jobs = JobStore(tmp_path, executor, fail)
        submitted = jobs.submit("case", {})
        for _ in range(100):
            status = jobs.get(submitted["job_id"])
            if status["status"] == "failed":
                break
            time.sleep(.005)
        assert status["status"] == "failed"
        assert "covariance" in status["error"]["message"]
        assert "result" not in status


def test_large_json_is_gzipped_only_when_accepted(client, tmp_path):
    runtime = tmp_path / "artifacts" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "metrics.json").write_text(json.dumps({"status": "completed", "padding": "x" * 5000}))
    plain = client.get("/api/evidence")
    assert "Content-Encoding" not in plain.headers
    compressed = client.get("/api/evidence", headers={"Accept-Encoding": "gzip"})
    assert compressed.headers["Content-Encoding"] == "gzip"
    import gzip
    assert json.loads(gzip.decompress(compressed.data)) == plain.get_json()


def test_population_endpoint_returns_columns(client):
    result = client.get("/api/population")
    assert result.status_code == 200
    assert result.get_json()["columns"]["c_object_type"] == ["DEBRIS"]
