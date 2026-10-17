"""Two-body propagation with explicit SI units and closest-approach refinement."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

MU_EARTH = 3.986004418e14  # m^3 s^-2


def derivative(_time, state):
    radius = np.linalg.norm(state[:3])
    if radius < 6.3e6:
        raise ValueError("Trajectory intersects the unsupported Earth region")
    return np.r_[state[3:], -MU_EARTH * state[:3] / radius ** 3]


def integrate(state, start: float, end: float, *, tight: bool = False):
    state = np.asarray(state, dtype=float)
    if state.shape != (6,) or not np.all(np.isfinite(state)):
        raise ValueError("Orbit state requires six finite SI values")
    if start == end:
        return lambda t: np.repeat(state[:, None], np.size(t), axis=1) if np.ndim(t) else state.copy()
    factor = 0.1 if tight else 1
    result = solve_ivp(derivative, (start, end), state, method="DOP853", dense_output=True,
                       rtol=1e-10 * factor, atol=np.r_[np.full(3, 1e-3), np.full(3, 1e-6)] * factor)
    if not result.success:
        raise ValueError(f"Orbit propagation failed: {result.message}")
    return result.sol


@dataclass
class Trajectory:
    before: object
    after: object | None = None
    burn_time_seconds: float | None = None

    def __call__(self, time):
        values = np.asarray(time)
        if self.after is None:
            return self.before(time)
        if values.ndim == 0:
            return (self.after if float(values) >= self.burn_time_seconds else self.before)(time)
        output = np.empty((6, values.size))
        mask = values >= self.burn_time_seconds
        if np.any(mask):
            output[:, mask] = self.after(values[mask])
        if np.any(~mask):
            output[:, ~mask] = self.before(values[~mask])
        return output


def propagate(state, horizon_seconds: float, *, tight=False) -> Trajectory:
    return Trajectory(integrate(state, 0, horizon_seconds, tight=tight))


def apply_burn(nominal: Trajectory, burn_time_seconds: float, delta_v_mps: float,
               horizon_seconds: float, *, tight=False) -> Trajectory:
    state = nominal(burn_time_seconds).copy()
    radial = state[:3] / np.linalg.norm(state[:3])
    angular_momentum = np.cross(state[:3], state[3:])
    normal = angular_momentum / np.linalg.norm(angular_momentum)
    transverse = np.cross(normal, radial)
    state[3:] += delta_v_mps * transverse
    return Trajectory(nominal.before, integrate(state, burn_time_seconds, horizon_seconds, tight=tight),
                      burn_time_seconds)


def closest_approaches(a: Trajectory, b: Trajectory, horizon_seconds: float,
                       step_seconds: float = 30) -> list[float]:
    """All sampled negative-to-positive derivative roots, plus endpoints.

    Burn discontinuities are split explicitly. A finer independent pass is
    used for evaluated recommendations, reducing sensitivity to grid spacing.
    """
    times = np.arange(0.0, horizon_seconds, step_seconds)
    times = np.unique(np.r_[times, horizon_seconds,
                           *[t for t in (a.burn_time_seconds, b.burn_time_seconds) if t is not None]])
    difference = b(times) - a(times)
    slopes = np.einsum("ij,ij->j", difference[:3], difference[3:])

    def slope(time):
        diff = b(time) - a(time)
        return float(diff[:3] @ diff[3:])

    found = [0.0, float(horizon_seconds)]
    for i in np.where((slopes[:-1] <= 0) & (slopes[1:] >= 0))[0]:
        if slopes[i] == 0:
            found.append(float(times[i]))
        else:
            found.append(float(brentq(slope, times[i], times[i + 1], xtol=1e-7)))
    return sorted(set(found))


def conservation_errors(trajectory: Trajectory, horizon_seconds: float) -> dict:
    states = trajectory(np.linspace(0, horizon_seconds, 301))
    energy = np.sum(states[3:] ** 2, axis=0) / 2 - MU_EARTH / np.linalg.norm(states[:3], axis=0)
    momentum = np.linalg.norm(np.cross(states[:3].T, states[3:].T), axis=1)
    return {"max_relative_energy_error": float(np.max(np.abs(energy / energy[0] - 1))),
            "max_relative_angular_momentum_error": float(np.max(np.abs(momentum / momentum[0] - 1)))}
