"""Constrained Bayesian optimisation of a burn over the continuous (burn time, signed delta-v) space.

"AI proposes, physics verifies": the objective |dv| is known analytically, so only the feasibility boundary is
learned. A Gaussian process (Matern 5/2, normalised inputs) is fit to a continuous safety margin returned by the
real physics rule; constrained expected improvement (expected reduction of |dv| times the probability of
feasibility) picks the next burn. Every candidate is scored by the exact physics function, and the final
recommendation is only ever an evaluated point that passes the rule (and the tighter numerical verification), else
the method abstains. No learned number is used in the final decision.

Search coordinates are ``(u, w)`` in ``[0,1] x [-1,1]``. ``u`` maps linearly to the burn parameter (burn time or
lead). ``w`` is a signed log warp of delta-v, ``dv = sign(w) * dv_max * DV_FLOOR ** (1 - |w|)``, because the
feasibility boundary sits at small |dv|. The no-action point is evaluated separately and first.
"""
from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field

import numpy as np

MARGIN_CLIP = 8.0     # safety margin in decades of Pc, clipped to [-8, 8]
DV_FLOOR = 0.005      # smallest searched |dv| as a fraction of dv_max
IMPOSSIBLE = -MARGIN_CLIP


def margin_from_pc(worst_pc: float | None, threshold: float) -> float:
    """log10(threshold) - log10(worst-case Pc), clipped. Positive means safe. Invalid evaluations are -clip."""
    if worst_pc is None or not math.isfinite(worst_pc):
        return IMPOSSIBLE
    return float(np.clip(math.log10(threshold) - math.log10(max(worst_pc, 1e-300)), -MARGIN_CLIP, MARGIN_CLIP))


@dataclass
class Point:
    t: float | None          # burn parameter (None = no action)
    dv: float                # signed delta-v, m/s
    margin: float
    feasible: bool
    u: float = 0.0
    w: float = 0.0

    @property
    def dv_abs(self) -> float:
        return abs(self.dv)


class Problem:
    """Interface. ``evaluate`` is the real physics rule; ``verify`` is the stricter independent re-check."""
    name = "problem"
    t_min = 0.0
    t_max = 1.0
    dv_max = 1.0

    def evaluate(self, t: float | None, dv: float) -> Point:  # pragma: no cover - interface
        raise NotImplementedError

    def verify(self, point: Point) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def grid(self) -> list[tuple[float | None, float]]:  # pragma: no cover - interface
        raise NotImplementedError

    # -- coordinates
    def phys(self, u: float, w: float) -> tuple[float, float]:
        t = self.t_min + float(np.clip(u, 0, 1)) * (self.t_max - self.t_min)
        w = float(np.clip(w, -1, 1))
        sign = -1.0 if w < 0 else 1.0
        return t, sign * self.dv_max * DV_FLOOR ** (1.0 - abs(w))

    def coords(self, t: float, dv: float) -> tuple[float, float]:
        u = (t - self.t_min) / (self.t_max - self.t_min)
        mag = 1.0 + math.log(max(abs(dv), 1e-12) / self.dv_max) / math.log(1.0 / DV_FLOOR)
        return float(np.clip(u, 0, 1)), float(np.clip(mag, 0, 1)) * (-1.0 if dv < 0 else 1.0)

    def evaluate_at(self, t: float, dv: float) -> Point:
        """Evaluate a physical (t, dv) and record its search coordinates."""
        p = self.evaluate(t, dv)
        p.u, p.w = self.coords(t, dv)
        return p

    def evaluate_uw(self, u: float, w: float) -> Point:
        t, dv = self.phys(u, w)
        p = self.evaluate(t, dv)
        p.u, p.w = u, w
        return p


@dataclass
class Result:
    method: str
    point: Point | None            # verified recommendation, None = abstain
    evaluations: int               # physics evaluations spent in the search (not counting verification)
    verifications: int
    seconds: float
    history: list = field(default_factory=list)

    @property
    def dv_abs(self) -> float | None:
        return None if self.point is None else self.point.dv_abs


def select_verified(problem: Problem, points: list[Point]) -> tuple[Point | None, int]:
    """Cheapest feasible point that also passes tight verification; walks up in |dv| if verification fails."""
    checked = 0
    for p in sorted((p for p in points if p.feasible), key=lambda q: (q.dv_abs, q.t or 0.0)):
        if p.t is None:
            return p, checked          # no action: nothing to re-propagate beyond the evaluated rule
        checked += 1
        if problem.verify(p):
            return p, checked
    return None, checked


def _finish(problem, method, points, started):
    chosen, checked = select_verified(problem, points)
    return Result(method, chosen, len(points), checked, time.perf_counter() - started,
                  [(p.t, p.dv, p.margin, p.feasible) for p in points])


def _start(problem: Problem):
    first = problem.evaluate(None, 0.0)
    return first, [first]


# ------------------------------------------------------------------------------------------------ baselines

def run_grid(problem: Problem) -> Result:
    """The existing candidate grid (no-action first), exactly as the planner screens it."""
    started = time.perf_counter()
    points = [problem.evaluate(t, dv) for t, dv in problem.grid()]
    return _finish(problem, "grid", points, started)


def run_random(problem: Problem, budget: int, seed: int, *, log_dv: bool = False, warm: Point | None = None) -> Result:
    """Random search at equal budget; uniform in signed dv (default) or in the log-warped dv."""
    started = time.perf_counter()
    first, points = _start(problem)
    rng = np.random.default_rng(seed)
    if warm is not None and len(points) < budget:
        points.append(problem.evaluate_at(warm.t, warm.dv))
    while not first.feasible and len(points) < budget:
        u = float(rng.uniform())
        if log_dv:
            w = float(rng.uniform(-1, 1))
            p = problem.evaluate_uw(u, w)
        else:
            t, _ = problem.phys(u, 0)
            p = problem.evaluate(t, float(rng.uniform(-1, 1)) * problem.dv_max)
        points.append(p)
    name = ("random_log" if log_dv else "random") + ("_warm" if warm is not None else "")
    return _finish(problem, name, points, started)


def fine_grid_shape(budget: int) -> tuple[int, int]:
    """(n_times, n_dv_per_sign) of a regular grid using at most ``budget - 1`` evaluations plus no-action."""
    n_t = max(2, int(round(math.sqrt(max(budget - 1, 2) / 2.0))))
    k = max(1, (budget - 1) // (2 * n_t))
    return n_t, k


def run_fine_grid(problem: Problem, budget: int) -> Result:
    started = time.perf_counter()
    first, points = _start(problem)
    n_t, k = fine_grid_shape(budget)
    if not first.feasible:
        times = np.linspace(problem.t_min, problem.t_max, n_t)
        mags = np.geomspace(problem.dv_max * DV_FLOOR * 2, problem.dv_max, k)
        for t in times:
            for m in mags:
                for sign in (1.0, -1.0):
                    points.append(problem.evaluate(float(t), sign * float(m)))
    return _finish(problem, "fine_grid", points, started)


# ------------------------------------------------------------------------------------------------ BO

def _gp(seed: int):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    kernel = (ConstantKernel(1.0, (1e-2, 1e2)) * Matern(length_scale=[0.3, 0.3], length_scale_bounds=(0.05, 3.0), nu=2.5)
              + WhiteKernel(1e-3, (1e-6, 1e-1)))
    return GaussianProcessRegressor(kernel, normalize_y=True, n_restarts_optimizer=1, random_state=seed)


def _norm_cdf(z):
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def _sobol(n: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc
    s = qmc.Sobol(2, scramble=True, seed=seed).random(n)
    return np.c_[s[:, 0], 2 * s[:, 1] - 1]


def run_bo(problem: Problem, budget: int, seed: int, *, warm: Point | None = None, n_init: int = 4,
           pool: int = 1024) -> Result:
    """Constrained BO. ``warm`` is a known physics-feasible burn (e.g. the grid's best) seeded as the incumbent."""
    started = time.perf_counter()
    first, points = _start(problem)
    rng = np.random.default_rng(seed)
    if not first.feasible:
        if warm is not None and len(points) < budget:
            points.append(problem.evaluate_at(warm.t, warm.dv))
        init = _sobol(max(n_init, 1), seed)
        for u, w in init:
            if len(points) >= min(budget, 1 + (warm is not None) + n_init):
                break
            points.append(problem.evaluate_uw(float(u), float(w)))
        static_pool = _sobol(pool, seed + 1)
        while len(points) < budget:
            pts = [p for p in points if p.t is not None]
            if not pts:
                break
            X = np.array([problem.coords(p.t, p.dv) for p in pts])
            y = np.array([p.margin for p in pts])
            gp = _gp(seed)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gp.fit(X, y)
            feasible = [p for p in pts if p.feasible]
            best = min((p.dv_abs for p in feasible), default=problem.dv_max * 1.0000001)
            cands = [static_pool]
            if feasible:
                inc = min(feasible, key=lambda p: p.dv_abs)
                cu, cw = problem.coords(inc.t, inc.dv)
                for sd in (0.03, 0.1, 0.25):
                    cands.append(np.c_[np.clip(cu + sd * rng.standard_normal(96), 0, 1),
                                       np.clip(cw + sd * rng.standard_normal(96), -1, 1)])
                shrink = np.clip(abs(cw) - rng.uniform(0, 0.25, 96), 0, 1) * (1 if cw >= 0 else -1)
                cands.append(np.c_[np.clip(cu + 0.05 * rng.standard_normal(96), 0, 1), shrink])
            C = np.vstack(cands)
            seen = np.array([(p.u, p.w) for p in pts])
            mask = np.min(np.abs(C[:, None, :] - seen[None, :, :]).max(axis=2), axis=1) > 1e-3
            if mask.any():
                C = C[mask]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mu, sd = gp.predict(C, return_std=True)
            sd = np.maximum(sd, 1e-9)
            pf = _norm_cdf(mu / sd)
            dv_abs = np.array([abs(problem.phys(u, w)[1]) for u, w in C])
            acq = np.maximum(best - dv_abs, 0.0) * pf
            idx = int(np.argmax(acq)) if acq.max() > 1e-12 else int(np.argmax(mu + 2 * sd))
            points.append(problem.evaluate_uw(float(C[idx, 0]), float(C[idx, 1])))
    return _finish(problem, "bo_warm" if warm is not None else "bo", points, started)


# ------------------------------------------------------------------------------------------------ statistics

def bootstrap_median_ci(values, seed: int = 0, n: int = 10000, alpha: float = 0.05) -> dict:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return {"n": 0, "median": None, "lo": None, "hi": None}
    rng = np.random.default_rng(seed)
    meds = np.median(v[rng.integers(0, v.size, (n, v.size))], axis=1)
    return {"n": int(v.size), "median": float(np.median(v)), "lo": float(np.quantile(meds, alpha / 2)),
            "hi": float(np.quantile(meds, 1 - alpha / 2))}
