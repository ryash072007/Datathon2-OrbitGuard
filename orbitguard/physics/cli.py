"""Reproducible validation, stress-test evaluation and runtime measurement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from .planner import BURN_TIMES, DELTA_V_OPTIONS, RISK_THRESHOLD, UNCERTAINTY_SCALES, screen_scenario
from .scenarios import ASSUMPTIONS, get_scenario, suite_ids
from .validation import environment_metadata, validate_physics, write_json


def _suite_manifest(scenarios):
    return {"suite_version": "1", "source": "synthetic",
            "distribution": {"clear": 10, "primary": 10, "secondary": 20, "blocked": 10},
            "construction_disclosure": "Secondary cases deliberately place C on a primary-only-selected path. This is a stress-test distribution, not real-world event prevalence.",
            "scenarios": [{"scenario_id": s.scenario_id, "seed": s.seed, "kind": s.kind,
                           "horizon_seconds": s.horizon_seconds, "primary_tca_seconds": s.primary_tca_seconds,
                           "secondary_tca_seconds": s.secondary_tca_seconds, "construction": s.metadata,
                           "objects": [{"object_id": o.object_id, "state_si": o.state.tolist(),
                                        "sigma_rtn_m": list(o.sigma_rtn_m), "radius_m": o.radius_m} for o in s.objects]}
                          for s in scenarios]}


def _aggregate(results, policy_name):
    policies = [r["policies"][policy_name] for r in results if "policies" in r]
    accepted = sum(p["accepted"] for p in policies)
    abstentions = sum(p.get("abstained", False) for p in policies)
    feasible = [any(c["accepted"] for c in r["candidates"]) for r in results if "policies" in r]
    nonabstained = [p for p in policies if not p.get("abstained")]
    return {"acceptable_plan_count": accepted, "acceptable_plan_rate": accepted / len(results) if results else 0,
            "abstentions": abstentions,
            "correct_abstentions": sum(p.get("abstained", False) and not f for p, f in zip(policies, feasible)),
            "secondary_hazards_introduced": sum(p["introduced_secondary_hazard"] for p in policies),
            "unsafe_selected_count": sum(not p["accepted"] for p in nonabstained),
            "numerical_verification_failures": sum(p.get("verification", {}).get("status") == "failed" for p in policies),
            "mean_delta_v_mps": float(np.mean([abs(p["delta_v_mps"]) for p in nonabstained])) if nonabstained else None,
            "mean_worst_pc": float(np.mean([p["worst_pc"] for p in nonabstained if p["worst_pc"] is not None])) if any(p["worst_pc"] is not None for p in nonabstained) else None,
            "max_worst_pc": max((p["worst_pc"] for p in nonabstained if p["worst_pc"] is not None), default=None)}


def benchmark_planner(root: Path, count=50, *, runtime_repetitions=20) -> dict:
    directory = root / "artifacts" / "physics"
    started = time.perf_counter()
    scenarios = [get_scenario(name) for name in suite_ids()[:count]]
    manifest = _suite_manifest(scenarios)
    serialized = json.dumps(manifest, sort_keys=True, allow_nan=False).encode()
    manifest_hash = hashlib.sha256(serialized).hexdigest()
    # Inputs are persisted before policy outcomes are computed.
    write_json(directory / "scenario_suite.json", manifest)
    results = []
    for index, scenario in enumerate(scenarios):
        try:
            result = screen_scenario(scenario, include_trajectories=False)
        except Exception as exc:
            result = {"scenario_id": scenario.scenario_id, "kind": scenario.kind, "status": "failed",
                      "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        write_json(directory / "runs" / f"{scenario.scenario_id}.json", result)
        print(f"Physics scenario {index + 1}/{count}: {scenario.scenario_id} {result['status']}", flush=True)
    policies = {name: _aggregate(results, name) for name in ("no_action", "pair_only", "orbitguard")}
    successful = [r for r in results if "policies" in r]
    benchmark = {"status": "complete" if len(successful) == count else "completed_with_failures",
                 "scenario_count": count, "failed_scenarios": count - len(successful),
                 "suite_sha256": manifest_hash, "suite_version": "1", "source": "synthetic",
                 "suite_distribution": {kind: sum(s.kind == kind for s in scenarios) for kind in ("clear", "primary", "secondary", "blocked")},
                 "construction_disclosure": manifest["construction_disclosure"], "policies": policies,
                 "introduced_secondary_hazard_definition": "A selected policy exceeds the threshold for another object while no action does not; both use the maximum across all three uncertainty settings.",
                 "by_kind": {kind: {name: _aggregate([r for r in results if r["kind"] == kind], name)
                                     for name in policies} for kind in ("clear", "primary", "secondary", "blocked") if any(r["kind"] == kind for r in results)},
                 "risk_threshold": RISK_THRESHOLD, "uncertainty_scales": list(UNCERTAINTY_SCALES),
                 "candidate_grid": {"burn_times_seconds": list(BURN_TIMES), "delta_v_mps": list(DELTA_V_OPTIONS), "includes_no_action": True},
                 "elapsed_seconds": time.perf_counter() - started,
                 "latency_ms": {"p50": float(np.percentile([r["elapsed_ms"] for r in successful], 50)),
                                "p95": float(np.percentile([r["elapsed_ms"] for r in successful], 95))} if successful else None,
                 "scenarios": [{key: r[key] for key in ("scenario_id", "kind", "status", "policies") if key in r} for r in results],
                 "assumptions": ASSUMPTIONS, **environment_metadata()}
    write_json(directory / "benchmark.json", benchmark)
    # Save a real UI-ready demonstration run, separately from benchmark data.
    demonstration = screen_scenario(get_scenario("chain-reaction"))
    write_json(directory / "demonstration.json", demonstration)
    if runtime_repetitions:
        benchmark_runtime(root, runtime_repetitions)
    return benchmark


def benchmark_runtime(root: Path, repetitions=20) -> dict:
    scenario = get_scenario("chain-reaction")
    screen_scenario(scenario, include_trajectories=False)  # documented warm-up
    durations = []
    for _ in range(repetitions):
        started = time.perf_counter()
        screen_scenario(scenario, include_trajectories=False)
        durations.append((time.perf_counter() - started) * 1000)
    result = {"status": "complete", "workload": "37 candidates, 8 objects, 3-hour horizon, 3 uncertainty scales, tighter verification",
              "mode": "serial", "workers": 1, "warmup_runs": 1, "measured_runs": repetitions,
              "includes_scenario_generation": False, "includes_trajectories_serialization": False,
              "latency_ms": {"p50": float(np.percentile(durations, 50)), "p95": float(np.percentile(durations, 95)),
                             "min": min(durations), "max": max(durations)}, "samples_ms": durations,
              "target_p95_ms": 5000, "target_met": float(np.percentile(durations, 95)) < 5000,
              **environment_metadata()}
    write_json(root / "artifacts" / "physics" / "runtime.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-physics", "benchmark-planner", "benchmark-physics-runtime"))
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("ORBITGUARD_ROOT", Path.cwd())))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--runtime-repetitions", type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 50:
        parser.error("--count must be between 1 and 50")
    if args.runtime_repetitions < 0:
        parser.error("--runtime-repetitions must be nonnegative")
    if args.command == "validate-physics":
        result = validate_physics()
        write_json(args.root / "artifacts" / "physics" / "validation.json", result)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result["passed"] else 1
    if args.command == "benchmark-physics-runtime":
        if args.runtime_repetitions < 1:
            parser.error("Runtime benchmarking requires at least one repetition")
        result = benchmark_runtime(args.root, args.runtime_repetitions)
    else:
        result = benchmark_planner(args.root, args.count, runtime_repetitions=args.runtime_repetitions)
    print(json.dumps({k: v for k, v in result.items() if k not in {"scenarios", "by_kind", "assumptions", "samples_ms"}}, indent=2))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
