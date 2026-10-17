"""Published reference checks plus numerical invariants; no network required."""

from __future__ import annotations

import json
import math
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy

from .orbits import conservation_errors, propagate
from .risk import collision_probability, disk_probability

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nasa_circular.json"


def environment_metadata() -> dict:
    return {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "architecture": platform.machine(), "platform": platform.platform(),
            "python_version": platform.python_version(), "numpy_version": np.__version__,
            "scipy_version": scipy.__version__}


def validate_physics() -> dict:
    fixtures = json.loads(FIXTURE_PATH.read_text())
    cases = []
    for fixture in fixtures["cases"]:
        keys = ("r1_m", "v1_mps", "cov1_m2", "r2_m", "v2_mps", "cov2_m2", "hard_body_radius_m")
        actual = collision_probability(*(fixture[key] for key in keys))
        expected = fixture["expected_pc"]
        relative_error = abs(actual / expected - 1)
        cases.append({"name": fixture["name"], "expected": expected, "actual": actual,
                      "relative_error": relative_error, "relative_tolerance": fixture["relative_tolerance"],
                      "passed": relative_error <= fixture["relative_tolerance"], "source": fixture["source"]})
    sigma, radius = 35.0, 10.0
    actual = disk_probability([0, 0], np.eye(2) * sigma ** 2, radius)
    expected = -math.expm1(-radius ** 2 / (2 * sigma ** 2))
    checks = [{"name": "Centred isotropic analytic integral", "expected": expected, "actual": actual,
               "passed": abs(actual - expected) < 1e-11}]
    fixture = fixtures["cases"][0]
    r1, v1, c1, r2, v2, c2 = [np.asarray(fixture[key]) for key in ("r1_m", "v1_mps", "cov1_m2", "r2_m", "v2_mps", "cov2_m2")]
    radius = fixture["hard_body_radius_m"]
    original = collision_probability(r1, v1, c1, r2, v2, c2, radius)
    theta = 0.713
    rotation = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    rotated = collision_probability(rotation @ r1, rotation @ v1, rotation @ c1 @ rotation.T,
                                    rotation @ r2, rotation @ v2, rotation @ c2 @ rotation.T, radius)
    swapped = collision_probability(r2, v2, c2, r1, v1, c1, radius)
    larger = collision_probability(r1, v1, c1, r2, v2, c2, radius * 1.5)
    checks.extend([
        {"name": "Common rotation invariance", "expected": original, "actual": rotated,
         "passed": abs(rotated / original - 1) < 1e-7},
        {"name": "Object exchange invariance", "expected": original, "actual": swapped,
         "passed": abs(swapped / original - 1) < 1e-9},
        {"name": "Hard-body radius monotonicity", "expected": f">= {original}", "actual": larger,
         "passed": larger >= original},
    ])
    try:
        collision_probability(r1, v1, -np.eye(3), r2, v2, c2, radius)
        rejected = False
    except ValueError:
        rejected = True
    checks.append({"name": "Invalid covariance is rejected", "actual": rejected, "expected": True, "passed": rejected})
    from .scenarios import get_scenario
    scenario = get_scenario("primary-only")
    errors = conservation_errors(propagate(scenario.objects[0].state, scenario.horizon_seconds), scenario.horizon_seconds)
    checks.extend({"name": name.replace("_", " "), "actual": value, "expected": "< 1e-8", "passed": value < 1e-8}
                  for name, value in errors.items())
    return {"status": "complete", "passed": all(c["passed"] for c in cases + checks),
            "reference_commit": fixtures["reference_commit"], "attribution": fixtures["attribution"],
            "case_count": len(cases), "cases": cases, "numerical_checks": checks,
            "limitation": "Verifies selected probability calculations and propagation invariants; not operational validation of the complete planner.",
            **environment_metadata()}


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
