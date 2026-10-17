"""Constrained-BO burn search: every recommendation must pass the exact physics rule."""
import math

import pytest

from orbitguard.optimise import run as R
from orbitguard.optimise import search as S
from orbitguard.physics.scenarios import get_scenario

BUDGET = 10


@pytest.fixture(scope="module")
def primary_problem():
    return R.SyntheticProblem(get_scenario("eval-10"))


@pytest.fixture(scope="module")
def grid_result(primary_problem):
    return S.run_grid(primary_problem)


def test_margin_sign_and_clip():
    assert S.margin_from_pc(1e-6, 1e-4) == pytest.approx(2.0)
    assert S.margin_from_pc(1e-3, 1e-4) == pytest.approx(-1.0)
    assert S.margin_from_pc(0.0, 1e-4) == S.MARGIN_CLIP
    assert S.margin_from_pc(None, 1e-4) == S.IMPOSSIBLE
    assert S.margin_from_pc(float("nan"), 1e-4) == S.IMPOSSIBLE


def test_coordinate_roundtrip(primary_problem):
    for t, dv in ((300.0, 0.05), (900.0, -0.5), (1500.0, 1.0)):
        u, w = primary_problem.coords(t, dv)
        t2, dv2 = primary_problem.phys(u, w)
        assert t2 == pytest.approx(t) and dv2 == pytest.approx(dv)


def test_grid_matches_planner_screen(grid_result):
    from orbitguard.physics.planner import screen_scenario
    ref = screen_scenario(get_scenario("eval-10"), include_trajectories=False)
    assert grid_result.evaluations == ref["candidates_evaluated"]
    assert grid_result.point is not None
    assert abs(grid_result.point.dv) == pytest.approx(abs(ref["recommendation"]["delta_v_mps"]))


def test_bo_recommendation_is_physics_feasible(primary_problem):
    result = S.run_bo(primary_problem, BUDGET, seed=0)
    assert result.evaluations <= BUDGET
    if result.point is not None:
        assert result.point.feasible
        # independent tight-tolerance physics check of the returned burn
        assert primary_problem.verify(result.point)


def test_never_worse_than_grid_when_seeded(primary_problem, grid_result):
    warm = grid_result.point
    result = S.run_bo(primary_problem, BUDGET, seed=1, warm=warm)
    assert result.point is not None
    assert result.point.dv_abs <= warm.dv_abs + 1e-12
    assert primary_problem.verify(result.point)


def test_impossible_scenario_abstains():
    problem = R.SyntheticProblem(get_scenario("eval-45"))     # encounter before the first permitted burn
    for result in (S.run_bo(problem, 8, seed=0), S.run_random(problem, 8, 0), S.run_fine_grid(problem, 8)):
        assert result.point is None


def test_clear_scenario_needs_no_burn():
    problem = R.SyntheticProblem(get_scenario("eval-00"))
    result = S.run_bo(problem, BUDGET, seed=0)
    assert result.point is not None and result.point.dv == 0.0 and result.evaluations == 1


def test_deterministic(primary_problem):
    a = S.run_bo(primary_problem, BUDGET, seed=3)
    b = S.run_bo(primary_problem, BUDGET, seed=3)
    assert a.history == b.history
    assert (a.point is None) == (b.point is None)
    r1 = S.run_random(primary_problem, BUDGET, seed=3)
    r2 = S.run_random(primary_problem, BUDGET, seed=3)
    assert r1.history == r2.history


def test_bootstrap_ci_contains_median():
    ci = S.bootstrap_median_ci([0.8, 0.9, 1.0, 0.7, 0.95], seed=0)
    assert ci["lo"] <= ci["median"] <= ci["hi"]
    assert S.bootstrap_median_ci([])["median"] is None


def test_run_synthetic_writes_evidence(tmp_path):
    ev = R.run_synthetic(2, BUDGET, 0, out_dir=tmp_path, progress=False)
    assert (tmp_path / "evidence.json").exists()
    assert math.isfinite(ev["elapsed_seconds"]) and ev["platform"]["byteorder"] in ("little", "big")
    assert ev["designed_impossible_all_abstain"] in (True, False)
    assert ev["one_line_summary"].startswith("2 scenarios")
