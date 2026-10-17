"""Machine provenance and repeatable inference/planning latency measurements."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

from orbitguard.api import available_cpus, json_safe, _screen_worker


def environment_info() -> dict:
    packages = {}
    for name in ["orbitguard", "Flask", "gunicorn", "numpy", "scipy", "pandas", "scikit-learn", "joblib", "threadpoolctl"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    try:
        checked = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3)
        commit = checked.stdout.strip() if checked.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    return {
        "architecture": platform.machine(),
        "platform": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "is_linuxone": platform.machine() == "s390x",
        "available_cpus": available_cpus(),
        "packages": packages,
        "source_commit": commit,
    }


def summary(samples_ms: list[float]) -> dict:
    if not samples_ms:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    ordered = sorted(samples_ms)
    # Explicit nearest-rank percentile, identical across NumPy/library versions.
    import math
    return {
        "count": len(samples_ms),
        "p50_ms": statistics.median(samples_ms),
        "p95_ms": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def benchmark(root: Path, forecast_runs: int = 100, screening_runs: int = 20, warmup: int = 20) -> dict:
    from threadpoolctl import threadpool_limits
    from orbitguard.ml.service import MLService
    from orbitguard.physics.service import PhysicsService

    start = time.perf_counter()
    result = {
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": environment_info(),
        "methodology": {
            "clock": "time.perf_counter",
            "percentile": "nearest-rank p95; median p50",
            "scope": "Python service calls; excludes browser/network overhead",
            "numerical_threads_per_worker": 1,
            "forecast_warmup_runs": warmup,
            "screening_cache": "No cached screening-result reuse; unchanged trajectory geometry may be cached by service.",
        },
    }
    ml = MLService(root)
    physics = PhysicsService(root)
    with threadpool_limits(limits=1):
        events = ml.list_events(min(100, max(1, forecast_runs)))
        histories = []
        for event in events:
            detail = ml.get_event(str(event["event_id"]))
            history = detail.get("history", detail.get("messages"))
            if history:
                histories.append(history)
        failures = []
        timings = []
        if histories:
            for i in range(warmup):
                ml.forecast(histories[i % len(histories)])
            for i in range(forecast_runs):
                before = time.perf_counter()
                try:
                    ml.forecast(histories[i % len(histories)])
                    timings.append((time.perf_counter() - before) * 1000)
                except Exception as exc:
                    failures.append(str(exc))
        else:
            failures.append("No eligible historical examples available.")
        result["forecast"] = {**summary(timings), "failures": failures, "unique_events": len(histories),
                              "target_p95_ms": 250, "target_met": bool(timings) and summary(timings)["p95_ms"] < 250}
        scenarios = physics.list_scenarios()
        identifiers = [s["scenario_id"] for s in scenarios]
        if not identifiers:
            raise ValueError("No simulator scenarios available for benchmarking")
        # One explicit warm-up establishes imports before service-call measurements.
        physics.screen(identifiers[0])
        screening_timings = []
        screening_failures = []
        candidate_counts = []
        for i in range(screening_runs):
            before = time.perf_counter()
            try:
                output = physics.screen(identifiers[i % len(identifiers)])
                screening_timings.append((time.perf_counter() - before) * 1000)
                candidate_counts.append(output.get("candidates_evaluated"))
            except Exception as exc:
                screening_failures.append(str(exc))
        result["screening"] = {**summary(screening_timings), "failures": screening_failures,
                               "scenario_ids": identifiers, "candidates_evaluated_per_run": candidate_counts,
                               "target_p95_ms": 5000,
                               "target_met": bool(screening_timings) and summary(screening_timings)["p95_ms"] < 5000}
        tasks = [(str(root), identifiers[i % len(identifiers)], {}) for i in range(screening_runs)]
        workers = max(1, min(available_cpus(), 4))
        before = time.perf_counter()
        serial_failures = 0
        for task in tasks:
            try:
                _screen_worker(*task)
            except Exception:
                serial_failures += 1
        serial_seconds = time.perf_counter() - before
        before = time.perf_counter()
        parallel_failures = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_screen_worker, *task) for task in tasks]
            for future in futures:
                try:
                    future.result()
                except Exception:
                    parallel_failures += 1
        parallel_seconds = time.perf_counter() - before
        result["parallel_comparison"] = {
            "workloads": len(tasks), "workers": workers,
            "serial_seconds": serial_seconds, "parallel_seconds": parallel_seconds,
            "speedup": serial_seconds / parallel_seconds if parallel_seconds else None,
            "serial_failures": serial_failures, "parallel_failures": parallel_failures,
            "includes_process_pool_startup": True,
        }
    if result["forecast"]["failures"] or result["screening"]["failures"] or serial_failures or parallel_failures:
        result["status"] = "completed_with_failures"
    result["total_seconds"] = time.perf_counter() - start
    # Models, evidence and raw data remain separate. Preserve the exact model
    # fingerprint used by the services whenever the evidence exposes one.
    result["model_evidence"] = {k: v for k, v in ml.evidence().items() if k in {"model_name", "model_version", "model_sha256", "selected_method"}}
    result = json_safe(result)
    destination = root / "artifacts" / "runtime"
    destination.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, allow_nan=False)
    (destination / "metrics.json").write_text(encoded)
    (destination / "metrics.sha256").write_text(hashlib.sha256(encoded.encode()).hexdigest() + "\n")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="orbitguard benchmark-runtime")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("ORBITGUARD_ROOT", ".")))
    parser.add_argument("--forecast-runs", type=int, default=100)
    parser.add_argument("--screening-runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=20)
    options = parser.parse_args(argv)
    if options.forecast_runs < 1 or options.screening_runs < 1 or options.warmup < 0:
        parser.error("Run counts must be positive and warmup nonnegative")
    result = benchmark(options.root.resolve(), options.forecast_runs, options.screening_runs, options.warmup)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["status"] == "completed" else 1
