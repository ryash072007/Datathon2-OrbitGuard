"""HTTP interface and bounded asynchronous screening jobs."""

from __future__ import annotations

import atexit
import gzip
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import platform
import threading
import time
from typing import Any
import uuid

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from orbitguard import __version__

LOG = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    """Keep numerical results valid JSON without inventing finite measurements."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return json_safe(value.item())
    if hasattr(value, "tolist"):
        return json_safe(value.tolist())
    return value


def _screen_worker(root: str, scenario_id: str, overrides: dict) -> dict:
    # Import inside the worker: no model or scientific-library initialization at
    # web-service startup, and no inherited mutable estimator between processes.
    from threadpoolctl import threadpool_limits
    from orbitguard.physics.service import PhysicsService

    with threadpool_limits(limits=1):
        return json_safe(PhysicsService(Path(root)).screen(scenario_id, overrides))


def available_cpus() -> int:
    count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    quota = Path("/sys/fs/cgroup/cpu.max")
    if quota.exists():
        try:
            maximum, period = quota.read_text().split()
            if maximum != "max":
                count = min(count, max(1, math.ceil(int(maximum) / int(period))))
        except (OSError, ValueError):
            pass
    return max(1, count)


class JobStore:
    """Finite queue with durable, downloadable completed runs."""

    def __init__(self, root: Path, executor: Executor | None = None, worker=None, max_pending: int = 8):
        self.root = root
        self.executor = executor
        self.worker = worker or _screen_worker
        self.max_pending = max_pending
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()

    def submit(self, scenario_id: str, overrides: dict) -> dict:
        with self.lock:
            pending = sum(j["status"] in {"queued", "running"} for j in self.jobs.values())
            if pending >= self.max_pending:
                raise OverflowError("The screening queue is full. Wait for a running job to finish.")
            if self.executor is None:
                configured = int(os.environ.get("ORBITGUARD_WORKERS", "2"))
                workers = max(1, min(configured, available_cpus(), 4))
                self.executor = ProcessPoolExecutor(max_workers=workers)
            job_id = str(uuid.uuid4())
            job = {
                "job_id": job_id,
                "status": "queued",
                "scenario_id": scenario_id,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "started_monotonic": time.perf_counter(),
            }
            self.jobs[job_id] = job
            try:
                future = self.executor.submit(self.worker, str(self.root), scenario_id, overrides)
            except Exception:
                del self.jobs[job_id]
                raise
            job["future"] = future
            future.add_done_callback(lambda completed: self._complete(job_id, completed))
            return {"job_id": job_id, "status": "queued"}

    def _complete(self, job_id: str, future: Future) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["elapsed_seconds"] = time.perf_counter() - job["started_monotonic"]
            try:
                result = future.result()
                result = json_safe(result)
                # Reject incompatible/non-JSON output before publishing success.
                json.dumps(result, allow_nan=False)
                job.update(status="completed", result=result)
            except Exception as exc:
                LOG.exception("Screening job %s failed", job_id)
                job.update(status="failed", error={"code": "screening_failed", "message": str(exc)})
            payload = self._public(job)
            try:
                directory = self.root / "artifacts" / "runs"
                directory.mkdir(parents=True, exist_ok=True)
                temporary = directory / f".{job_id}.tmp"
                temporary.write_text(json.dumps(payload, indent=2, allow_nan=False))
                temporary.replace(directory / f"{job_id}.json")
            except OSError:
                LOG.exception("Could not persist completed run %s", job_id)

    @staticmethod
    def _public(job: dict) -> dict:
        payload = {k: v for k, v in job.items() if k not in {"future", "started_monotonic"}}
        if payload["status"] in {"queued", "running"}:
            payload["status"] = "running" if job["future"].running() else "queued"
            payload["elapsed_seconds"] = time.perf_counter() - job["started_monotonic"]
        return payload

    def get(self, job_id: str) -> dict:
        try:
            uuid.UUID(job_id)
        except (ValueError, TypeError):
            raise KeyError(job_id) from None
        with self.lock:
            if job_id in self.jobs:
                return self._public(self.jobs[job_id])
        saved = self.root / "artifacts" / "runs" / f"{job_id}.json"
        if saved.is_file():
            return json.loads(saved.read_text())
        raise KeyError(job_id)

    def shutdown(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)


def create_app(root: str | Path | None = None, *, ml_service=None, physics_service=None,
               job_executor: Executor | None = None, screen_worker=None) -> Flask:
    root = Path(root or os.environ.get("ORBITGUARD_ROOT") or Path(__file__).resolve().parents[1]).resolve()
    if ml_service is None:
        from orbitguard.ml.service import MLService
        ml_service = MLService(root)
    if physics_service is None:
        from orbitguard.physics.service import PhysicsService
        physics_service = PhysicsService(root)
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024, JSON_SORT_KEYS=False)
    jobs = JobStore(root, job_executor, screen_worker)
    app.extensions["orbitguard_jobs"] = jobs
    atexit.register(jobs.shutdown)

    def response(data, status=200):
        return jsonify(json_safe(data)), status

    def body() -> dict:
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    @app.after_request
    def headers(result):
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            result.headers["Cache-Control"] = "no-store"
        # Evidence responses are a few hundred kB; compress them for SSH-tunnelled demos.
        if result.status_code == 200 and result.direct_passthrough and result.mimetype in {"text/javascript", "text/css"}:
            # Built frontend bundles are streamed from disk; buffer them so they can be compressed too.
            result.direct_passthrough = False
        if (result.status_code == 200 and not result.direct_passthrough
                and "gzip" in request.headers.get("Accept-Encoding", "")
                and result.mimetype in {"application/json", "text/javascript", "text/css", "text/html"}
                and "Content-Encoding" not in result.headers):
            data = result.get_data()
            if len(data) > 1024:
                result.set_data(gzip.compress(data, compresslevel=5))
                result.headers["Content-Encoding"] = "gzip"
                result.headers["Vary"] = "Accept-Encoding"
        return result

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return response({"error": {"code": exc.name.lower().replace(" ", "_"), "message": exc.description}}, exc.code)
        if isinstance(exc, KeyError):
            return response({"error": {"code": "not_found", "message": "The requested event, scenario, or run does not exist."}}, 404)
        if isinstance(exc, ValueError):
            return response({"error": {"code": "invalid_input", "message": str(exc)}}, 422)
        if isinstance(exc, FileNotFoundError):
            return response({"error": {"code": "not_ready", "message": "Required data or model artifacts are not available yet."}}, 503)
        if isinstance(exc, OverflowError):
            return response({"error": {"code": "queue_full", "message": str(exc)}}, 429)
        LOG.exception("API request failed")
        return response({"error": {"code": "internal_error", "message": "The calculation failed. Check the server log for details."}}, 500)

    @app.get("/api/health")
    def health():
        model = ml_service.evidence()
        return response({
            "status": "ok",
            "architecture": platform.machine(),
            "platform": platform.system(),
            "is_linuxone": platform.machine() == "s390x",
            "available_cpus": available_cpus(),
            "model": {key: model.get(key) for key in ("status", "ready", "model_ready", "model_name", "model_version") if key in model},
            "build_version": __version__,
        })

    @app.get("/api/events")
    def events():
        try:
            limit = int(request.args.get("limit", 100))
        except ValueError:
            raise ValueError("limit must be an integer between 1 and 500") from None
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return response({"events": ml_service.list_events(limit)})

    @app.get("/api/population")
    def population():
        return response(ml_service.overview())

    @app.get("/api/events/<event_id>")
    def event(event_id):
        return response(ml_service.get_event(event_id))

    @app.post("/api/forecast")
    def forecast():
        history = body().get("history")
        if not isinstance(history, list) or not history or len(history) > 1000:
            raise ValueError("history must contain between 1 and 1000 CDM objects")
        if not all(isinstance(row, dict) for row in history):
            raise ValueError("Each history entry must be a CDM object")
        return response(ml_service.forecast(history))

    @app.get("/api/scenarios")
    def scenarios():
        return response({"scenarios": physics_service.list_scenarios()})

    @app.get("/api/scenarios/<scenario_id>")
    def scenario(scenario_id):
        return response(physics_service.get_scenario(scenario_id))

    @app.post("/api/screen")
    def screen():
        payload = body()
        scenario_id = payload.get("scenario_id")
        overrides = payload.get("overrides", {})
        if not isinstance(scenario_id, str) or not scenario_id or len(scenario_id) > 128:
            raise ValueError("scenario_id must be a nonempty string")
        if not isinstance(overrides, dict):
            raise ValueError("overrides must be a JSON object")
        # Validate identity before scheduling, avoiding an expensive failed job.
        physics_service.get_scenario(scenario_id)
        return response(jobs.submit(scenario_id, overrides), 202)

    @app.get("/api/jobs/<job_id>")
    def job(job_id):
        return response(jobs.get(job_id))

    @app.get("/api/runs/<job_id>")
    def run(job_id):
        payload = jobs.get(job_id)
        if payload["status"] not in {"completed", "failed"}:
            return response({"error": {"code": "not_finished", "message": "This run is still in progress."}}, 409)
        from io import BytesIO
        return send_file(BytesIO(json.dumps(json_safe(payload), indent=2, allow_nan=False).encode()),
                         mimetype="application/json", as_attachment=True, download_name=f"orbitguard-{job_id}.json")

    @app.get("/api/evidence")
    def evidence():
        runtime_path = root / "artifacts" / "runtime" / "metrics.json"
        runtime = json.loads(runtime_path.read_text()) if runtime_path.is_file() else {"status": "not_run"}
        return response({"ml": ml_service.evidence(), "physics": physics_service.evidence(), "runtime": runtime})

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path=""):
        if path.startswith("api/"):
            return response({"error": {"code": "not_found", "message": "Unknown API endpoint."}}, 404)
        dist = root / "frontend" / "dist"
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist) and candidate.is_file():
            return send_from_directory(dist, path)
        if path.startswith("assets/") or Path(path).suffix:
            return response({"error": {"code": "not_found", "message": "Asset not found."}}, 404)
        if (dist / "index.html").is_file():
            return send_from_directory(dist, "index.html")
        return response({"error": {"code": "frontend_not_built", "message": "Build the frontend with npm run build in frontend/."}}, 503)

    return app
