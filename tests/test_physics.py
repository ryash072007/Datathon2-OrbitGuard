import json
import math

import numpy as np
import pytest

from orbitguard.physics.orbits import Trajectory, closest_approaches, conservation_errors, propagate
from orbitguard.physics.planner import candidate_grid, screen_scenario, validate_overrides
from orbitguard.physics.risk import collision_probability, disk_probability
from orbitguard.physics.scenarios import get_scenario
from orbitguard.physics.service import PhysicsService
from orbitguard.physics.validation import FIXTURE_PATH, validate_physics


@pytest.mark.parametrize("fixture", json.loads(FIXTURE_PATH.read_text())["cases"], ids=lambda f: f["name"])
def test_published_nasa_circular_reference(fixture):
    actual = collision_probability(*(fixture[k] for k in
        ("r1_m", "v1_mps", "cov1_m2", "r2_m", "v2_mps", "cov2_m2", "hard_body_radius_m")))
    assert actual == pytest.approx(fixture["expected_pc"], rel=fixture["relative_tolerance"])


@pytest.mark.parametrize("sigma,radius", [(35, 10), (2, 3), (1000, 1)])
def test_analytic_isotropic_gaussian(sigma, radius):
    actual = disk_probability([0, 0], np.eye(2) * sigma ** 2, radius)
    assert actual == pytest.approx(-math.expm1(-radius ** 2 / (2 * sigma ** 2)), rel=1e-9)


def test_reference_invariants_and_conservation():
    result = validate_physics()
    assert result["passed"]
    assert all(check["passed"] for check in result["numerical_checks"])


def test_invalid_covariance_and_degenerate_velocity_rejected():
    args = ([7e6, 0, 0], [0, 7500, 0], np.eye(3), [7e6, 0, 10], [0, 7400, 100], np.eye(3), 10)
    for cov in (-np.eye(3), np.zeros((3, 3)), [[1, 2, 0], [0, 1, 0], [0, 0, 1]]):
        with pytest.raises(ValueError):
            collision_probability(args[0], args[1], cov, *args[3:])
    with pytest.raises(ValueError, match="relative velocity"):
        collision_probability(args[0], args[1], args[2], args[3], args[1], args[5], args[6])


def test_candidate_grid_and_override_validation():
    assert len(candidate_grid()) == 37
    assert candidate_grid(0) == [(None, 0)]
    for overrides in ({"risk_threshold": 0}, {"risk_threshold": float("nan")}, {"max_delta_v_mps": 2},
                      {"max_delta_v_mps": True}, {"unrecognised": 1}, []):
        with pytest.raises(ValueError):
            validate_overrides(overrides)


def test_chain_scenario_rejects_secondary_hazard_at_same_delta_v():
    result = screen_scenario(get_scenario("chain-reaction"))
    assert result["candidates_evaluated"] == 37
    pair, chosen = result["policies"]["pair_only"], result["policies"]["orbitguard"]
    assert pair["primary_pc"] <= result["risk_threshold"]
    assert pair["worst_secondary_pc"] > result["risk_threshold"]
    assert pair["introduced_secondary_hazard"]
    assert chosen["accepted"] and chosen["verification"]["accepted"]
    assert chosen["worst_pc"] <= result["risk_threshold"]
    assert abs(chosen["delta_v_mps"]) == abs(pair["delta_v_mps"])
    assert result["encounter_views"]["secondary"]["object_id"] == "C"
    json.dumps(result, allow_nan=False)


def test_clear_scenario_preserves_fuel():
    result = screen_scenario(get_scenario("clear-neighbourhood"), include_trajectories=False)
    assert result["recommendation"]["delta_v_mps"] == 0
    assert result["policies"]["orbitguard"]["accepted"]


def test_impossible_burn_and_zero_budget_explicitly_abstain():
    result = screen_scenario(get_scenario("no-feasible-burn"), include_trajectories=False)
    assert result["recommendation"] is None
    assert result["policies"]["orbitguard"]["abstained"]
    assert not any(c["accepted"] for c in result["candidates"])
    zero = screen_scenario(get_scenario("primary-only"), {"max_delta_v_mps": 0}, include_trajectories=False)
    assert zero["recommendation"] is None and zero["candidates_evaluated"] == 1


def test_service_missing_evidence_and_unknown_scenario(tmp_path):
    service = PhysicsService(tmp_path)
    assert not service.evidence()["ready"]
    assert len(service.list_scenarios()) == 4
    with pytest.raises(KeyError):
        service.get_scenario("unknown-scenario")
    detail = service.get_scenario("primary-only")
    assert len(detail["objects"]) == 8
    assert detail["source"] == "synthetic"
    json.dumps(detail, allow_nan=False)


def test_closest_approach_before_burn_uses_left_hand_velocity():
    def stationary(times):
        return np.zeros((6,) if np.ndim(times) == 0 else (6, len(times)))

    def before(times):
        values = np.asarray(times)
        return np.array([values - 4, values * 0 + 1, values * 0,
                         values * 0 + 1, values * 0, values * 0])

    def after(times):
        values = np.asarray(times)
        return np.array([values * 0 + 1, 1 - 10 * (values - 5), values * 0,
                         values * 0, values * 0 - 10, values * 0])

    times = closest_approaches(Trajectory(stationary), Trajectory(before, after, 5), 10, 10)
    assert times == pytest.approx([0, 4, 5.1, 10])


@pytest.mark.parametrize("mean", [[0, 0], [100, 100]])
def test_concentrated_gaussian_inside_large_disk_is_not_zero(mean):
    assert disk_probability(mean, np.eye(2), 1e6) == pytest.approx(1, abs=1e-10)


def test_tighter_verification_updates_risks_and_withholds_path(monkeypatch):
    from orbitguard.physics import planner

    monkeypatch.setattr(planner, "candidate_grid", lambda budget: [(None, 0), (300, 0.01)])

    def candidate(scenario, paths, burn, delta_v, threshold, *, tight=False):
        primary = threshold * (2 if burn is None else 0.5)
        secondary = threshold * (2 if tight and burn is not None else 0)
        worst = max(primary, secondary)
        return {"candidate_id": "no-action" if burn is None else "burn", "burn_time_seconds": burn,
                "delta_v_mps": delta_v, "primary_pc": primary, "worst_secondary_pc": secondary,
                "worst_pc": worst, "accepted": worst <= threshold,
                "primary_accepted": primary <= threshold, "valid": True,
                "rejection_reasons": [], "encounters": []}, paths["A"]

    monkeypatch.setattr(planner, "_candidate", candidate)
    result = screen_scenario(get_scenario("clear-neighbourhood"))
    assert result["recommendation"] is None
    pair = result["policies"]["pair_only"]
    assert pair["worst_secondary_pc"] == 2 * result["risk_threshold"]
    assert pair["worst_pc"] == pair["verification"]["worst_pc"]
    assert pair["verification"]["status"] == "rejected"
    assert pair["introduced_secondary_hazard"]
    assert not pair["accepted"]
    assert "A_orbitguard" not in {item["object_id"] for item in result["trajectories"]}
