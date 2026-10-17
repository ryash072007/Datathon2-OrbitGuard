"""SGP4 batch propagation, RTN frame, and manoeuvred trajectories by DELTA PROPAGATION.

Why delta propagation
---------------------
SGP4 cannot take a manoeuvre: it only knows mean elements from a TLE. A pure numerical re-propagation
of the burned state with a simple force model (two-body + J2) would disagree with the SGP4 baseline by
kilometres (drag, higher harmonics, mean/osculating differences), and that disagreement would swamp the
effect of a 0.01 m/s burn. Instead we integrate TWO states with the same simple integrator:

    A = SGP4 state at burn time                 (no burn)
    B = SGP4 state at burn time + dv (in RTN)   (burn)

and apply only the DIFFERENCE to the SGP4 trajectory:

    r_man(t) = r_sgp4(t) + [ J2(B)(t) - J2(A)(t) ]

Model errors common to A and B (the same J2-only force model) cancel to first order, so the baseline stays
exactly consistent with SGP4 and a zero burn reproduces SGP4 bit for bit. Neglected: drag/J3+ differences
between A and B (second order in dv) and TLE error itself (~1 km, no covariance is modelled).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sgp4.api import Satrec, SatrecArray, jday

MU = 398600.4418  # km^3/s^2
RE = 6378.137  # km
J2 = 1.08262668e-3
EPHEM_DTYPE = np.dtype("<f8")  # explicit little-endian: files are portable between s390x and x86


def as_utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def jd_fr(t0: datetime, offsets_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(jd, fr) arrays for SGP4 at t0 + offsets (seconds)."""
    t0 = as_utc(t0)
    jd0, fr0 = jday(t0.year, t0.month, t0.day, t0.hour, t0.minute, t0.second + t0.microsecond * 1e-6)
    offsets_s = np.asarray(offsets_s, dtype=np.float64)
    return np.full(offsets_s.shape, jd0), fr0 + offsets_s / 86400.0


def make_satrec(line1: str, line2: str) -> Satrec:
    return Satrec.twoline2rv(line1, line2)


def sgp4_track(sat: Satrec, t0: datetime, offsets_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """TEME position (km) and velocity (km/s) of one satellite, shape (T,3) each; NaN where SGP4 fails."""
    jd, fr = jd_fr(t0, offsets_s)
    e, r, v = sat.sgp4_array(jd, fr)
    bad = e != 0
    if bad.any():
        r = r.copy()
        v = v.copy()
        r[bad] = np.nan
        v[bad] = np.nan
    return r, v


def sgp4_grid(tles: list[tuple[str, str]], t0: datetime, n_steps: int, step_s: float = 60.0,
              block: int = 500) -> np.ndarray:
    """Vectorised SatrecArray propagation: positions (N, n_steps, 3) float64 in TEME km."""
    jd, fr = jd_fr(t0, np.arange(n_steps) * step_s)
    out = np.empty((len(tles), n_steps, 3), dtype=np.float64)
    for i0 in range(0, len(tles), block):
        sats = SatrecArray([make_satrec(a, b) for a, b in tles[i0:i0 + block]])
        e, r, _ = sats.sgp4(jd, fr)
        r = np.array(r)
        r[e != 0] = np.nan
        out[i0:i0 + block] = r
    return out


def write_ephemeris_memmap(tles: list[tuple[str, str]], t0: datetime, n_steps: int, path: Path,
                           step_s: float = 60.0, block: int = 500) -> None:
    """Write the catalogue ephemeris (N, n_steps, 3) as explicit '<f8' to ``path`` (workers re-open it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mm = np.memmap(path, dtype=EPHEM_DTYPE, mode="w+", shape=(len(tles), n_steps, 3))
    for i0 in range(0, len(tles), block):
        mm[i0:i0 + block] = sgp4_grid(tles[i0:i0 + block], t0, n_steps, step_s, block)
    mm.flush()
    del mm


def open_ephemeris(path: Path, n_objects: int, n_steps: int) -> np.memmap:
    return np.memmap(path, dtype=EPHEM_DTYPE, mode="r", shape=(n_objects, n_steps, 3))


# --------------------------------------------------------------------------- RTN frame

def rtn_basis(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rows are the unit vectors R (radial), T (along-track, completes the triad), N (orbit normal)."""
    r = np.asarray(r, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    rhat = r / np.linalg.norm(r, axis=-1, keepdims=True)
    n = np.cross(r, v)
    nhat = n / np.linalg.norm(n, axis=-1, keepdims=True)
    that = np.cross(nhat, rhat)
    return np.stack([rhat, that, nhat], axis=-2)


def rtn_to_inertial(vec_rtn: np.ndarray, r: np.ndarray, v: np.ndarray) -> np.ndarray:
    return np.asarray(vec_rtn, dtype=np.float64) @ rtn_basis(r, v)


# --------------------------------------------------------------------------- two-body + J2 integrator

def j2_accel(y: np.ndarray) -> np.ndarray:
    """Derivative of the state array y (K,6) = [x y z vx vy vz] under two-body + J2 (z = pole axis)."""
    x, yy, z = y[:, 0], y[:, 1], y[:, 2]
    r2 = x * x + yy * yy + z * z
    r = np.sqrt(r2)
    k = -MU / (r2 * r)
    f = 1.5 * J2 * (RE / r) ** 2
    z2 = 5.0 * z * z / r2
    d = np.empty_like(y)
    d[:, 0:3] = y[:, 3:6]
    d[:, 3] = k * x * (1.0 + f * (1.0 - z2))
    d[:, 4] = k * yy * (1.0 + f * (1.0 - z2))
    d[:, 5] = k * z * (1.0 + f * (3.0 - z2))
    return d


def integrate_j2(states: np.ndarray, n_steps: int, step_s: float = 10.0, out_every: int = 6) -> np.ndarray:
    """Fixed-step RK4, vectorised over K states. Returns (K, n_steps//out_every + 1, 6) incl. the initial state."""
    y = np.array(states, dtype=np.float64, copy=True).reshape(-1, 6)
    n_out = n_steps // out_every
    out = np.empty((n_out + 1, y.shape[0], 6))
    out[0] = y
    h = step_s
    for i in range(1, n_out * out_every + 1):
        k1 = j2_accel(y)
        k2 = j2_accel(y + 0.5 * h * k1)
        k3 = j2_accel(y + 0.5 * h * k2)
        k4 = j2_accel(y + h * k3)
        y = y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        if i % out_every == 0:
            out[i // out_every] = y
    return np.transpose(out, (1, 0, 2))


def delta_on_grid(r0: np.ndarray, v0: np.ndarray, dvs_rtn_kms: np.ndarray, kb: int, n_grid: int,
                  grid_step_s: float = 60.0, rk_step_s: float = 10.0) -> np.ndarray:
    """Delta propagation: (K, n_grid, 6) of [J2(state+dv)(t) - J2(state)(t)], zero for grid index < kb.

    ``r0, v0`` is the SGP4 state at grid index ``kb``; ``dvs_rtn_kms`` is (K,3) in km/s (R,T,N).
    """
    dvs = np.atleast_2d(np.asarray(dvs_rtn_kms, dtype=np.float64))
    out = np.zeros((dvs.shape[0], n_grid, 6))
    n_after = n_grid - 1 - kb
    if n_after <= 0 or not np.any(dvs):
        return out
    per = int(round(grid_step_s / rk_step_s))
    dv_inertial = rtn_to_inertial(dvs, r0, v0)
    base = np.concatenate([r0, v0])
    states = np.vstack([base[None, :]] + [base + np.concatenate([[0.0, 0.0, 0.0], dv]) for dv in dv_inertial])
    traj = integrate_j2(states, n_after * per, rk_step_s, per)
    out[:, kb:, :] = traj[1:] - traj[0:1]
    return out


def maneuvered_positions(sat: Satrec, t0: datetime, n_grid: int, kb: int, dv_rtn_kms: tuple[float, float, float],
                         grid_step_s: float = 60.0) -> tuple[np.ndarray, np.ndarray]:
    """(maneuvered positions (n_grid,3), SGP4 baseline positions (n_grid,3)) on the grid. dv zero -> identical."""
    offs = np.arange(n_grid) * grid_step_s
    base, vel = sgp4_track(sat, t0, offs)
    delta = delta_on_grid(base[kb], vel[kb], np.array([dv_rtn_kms]), kb, n_grid, grid_step_s)[0]
    return base + delta[:, :3], base


def orbital_period_s(sat: Satrec) -> float:
    return 2.0 * math.pi / sat.no_kozai * 60.0  # no_kozai is rad/min


def semi_major_axis_km(r: np.ndarray, v: np.ndarray) -> float:
    """Osculating semi-major axis from the vis-viva equation."""
    rn = float(np.linalg.norm(r))
    v2 = float(np.dot(v, v))
    return 1.0 / (2.0 / rn - v2 / MU)
