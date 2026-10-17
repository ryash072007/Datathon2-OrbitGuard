"""Debris-cloud evolution (two-body + J2 secular rates, no drag) and a spherical-bin density histogram.

Frame: SGP4's TEME, treated as inertial ECI throughout (no Earth rotation needed).
Each fragment becomes an orbit (a, e, orbit-plane unit vectors P, Q, normal W). At snapshot day d the plane is
rotated by the secular J2 rates (RAAN about z, argument of perigee about W) and the fragment is placed at K
RANDOM mean anomalies. Random anomalies assume the cloud is phase-mixed along the orbit at every snapshot; true
for fast fragments within days, optimistic dilution for the slowest ones in the first days (documented caveat).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from orbitguard.catalog.catalog import MU_KM3_S2 as MU, RE_KM as RE
from orbitguard.catalog.propagate import J2

PERIGEE_REENTRY_KM = 150.0
ALT_BIN_KM, LAT_BIN_DEG, RA_BIN_DEG = 10.0, 2.0, 5.0
N_ALT, N_LAT, N_RA = 400, 90, 72  # altitude range 0..4000 km; higher points are ignored
CELLS_PER_SNAPSHOT = N_ALT * N_LAT * N_RA


@dataclass
class DensityGrid:
    """Sparse histogram. keys sorted ascending; per key: weight sum, weight*v (3), weight*|v|^2."""
    keys: np.ndarray  # int64
    wsum: np.ndarray
    vsum: np.ndarray
    v2sum: np.ndarray
    k_samples: int

    @property
    def total_weight(self) -> float:
        return float(self.wsum.sum())


@dataclass
class OrbitSet:
    a: np.ndarray
    e: np.ndarray
    p_hat: np.ndarray
    q_hat: np.ndarray
    w_hat: np.ndarray
    weight: np.ndarray
    n_reentered: int
    n_unbound: int
    n_input: int


def to_orbits(pos: np.ndarray, vel: np.ndarray, weight: np.ndarray | float) -> OrbitSet:
    pos = np.asarray(pos, dtype=np.float64).reshape(-1, 3)
    vel = np.asarray(vel, dtype=np.float64).reshape(-1, 3)
    n_in = len(pos)
    w = np.broadcast_to(np.asarray(weight, dtype=np.float64), (n_in,)).copy()
    if n_in == 0:
        z3 = np.zeros((0, 3))
        return OrbitSet(np.zeros(0), np.zeros(0), z3, z3, z3, w, 0, 0, 0)
    r = np.linalg.norm(pos, axis=1)
    v2 = np.einsum("ij,ij->i", vel, vel)
    energy = 0.5 * v2 - MU / r
    bound = energy < 0
    a = np.where(bound, -MU / (2.0 * np.where(bound, energy, -1.0)), np.inf)
    h = np.cross(pos, vel)
    hn = np.linalg.norm(h, axis=1)
    evec = ((v2 - MU / r)[:, None] * pos - np.einsum("ij,ij->i", pos, vel)[:, None] * vel) / MU
    e = np.linalg.norm(evec, axis=1)
    perigee = a * (1.0 - e) - RE
    ok = bound & (e < 1.0) & (perigee >= PERIGEE_REENTRY_KM)
    n_unbound = int((~bound | (e >= 1.0)).sum())
    n_re = int((bound & (e < 1.0) & (perigee < PERIGEE_REENTRY_KM)).sum())
    w_hat = h[ok] / hn[ok, None]
    near_circ = e[ok] < 1e-6
    p_hat = np.where(near_circ[:, None], pos[ok] / r[ok, None], evec[ok] / np.maximum(e[ok], 1e-12)[:, None])
    q_hat = np.cross(w_hat, p_hat)
    return OrbitSet(a[ok], e[ok], p_hat, q_hat, w_hat, w[ok], n_re, n_unbound, n_in)


def j2_secular_rates(a: np.ndarray, e: np.ndarray, cos_i: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(RAAN rate, argument-of-perigee rate) in rad/s."""
    n = np.sqrt(MU / a**3)
    p = a * (1.0 - e**2)
    f = J2 * (RE / p) ** 2 * n
    return -1.5 * f * cos_i, 0.75 * f * (5.0 * cos_i**2 - 1.0)


def solve_kepler(m: np.ndarray, e: np.ndarray, iters: int = 12) -> np.ndarray:
    big_e = np.where(e < 0.8, m, np.pi)
    for _ in range(iters):
        big_e = big_e - (big_e - e * np.sin(big_e) - m) / (1.0 - e * np.cos(big_e))
    return big_e


def positions_at(orb: OrbitSet, t_s: float, k: int,
                 rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Positions/velocities (n*k,3) and weights of every fragment at k random mean anomalies after t_s of J2 drift."""
    n = len(orb.a)
    if n == 0:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0)
    raan_dot, argp_dot = j2_secular_rates(orb.a, orb.e, orb.w_hat[:, 2])
    dw, dO = argp_dot * t_s, raan_dot * t_s
    c, s = np.cos(dw)[:, None], np.sin(dw)[:, None]
    p = c * orb.p_hat + s * orb.q_hat
    q = -s * orb.p_hat + c * orb.q_hat
    cO, sO = np.cos(dO), np.sin(dO)

    def rz(x: np.ndarray) -> np.ndarray:
        return np.stack([cO * x[:, 0] - sO * x[:, 1], sO * x[:, 0] + cO * x[:, 1], x[:, 2]], axis=1)

    p, q = rz(p), rz(q)
    a, e = np.repeat(orb.a, k), np.repeat(orb.e, k)
    p, q = np.repeat(p, k, axis=0), np.repeat(q, k, axis=0)
    m = rng.uniform(0.0, 2.0 * math.pi, n * k)
    big_e = solve_kepler(m, e)
    ce, se = np.cos(big_e), np.sin(big_e)
    b = np.sqrt(1.0 - e**2)
    pos = (a * (ce - e))[:, None] * p + (a * b * se)[:, None] * q
    r = a * (1.0 - e * ce)
    vfac = np.sqrt(MU * a) / r
    vel = (-vfac * se)[:, None] * p + (vfac * b * ce)[:, None] * q
    return pos, vel, np.repeat(orb.weight, k)


def cell_indices(pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(flat cell index within a snapshot, in-range mask)."""
    r = np.linalg.norm(pos, axis=1)
    alt = r - RE
    lat = np.degrees(np.arcsin(np.clip(pos[:, 2] / r, -1.0, 1.0)))
    ra = np.degrees(np.arctan2(pos[:, 1], pos[:, 0])) % 360.0
    ia = np.floor(alt / ALT_BIN_KM).astype(np.int64)
    il = np.clip(np.floor((lat + 90.0) / LAT_BIN_DEG).astype(np.int64), 0, N_LAT - 1)
    ir = np.clip(np.floor(ra / RA_BIN_DEG).astype(np.int64), 0, N_RA - 1)
    ok = (ia >= 0) & (ia < N_ALT)
    return (np.clip(ia, 0, N_ALT - 1) * N_LAT + il) * N_RA + ir, ok


def cell_volume_km3(flat: np.ndarray) -> np.ndarray:
    rest = flat // N_RA
    il = rest % N_LAT
    ia = rest // N_LAT
    r1 = RE + ia * ALT_BIN_KM
    r2 = r1 + ALT_BIN_KM
    lat1 = np.radians(-90.0 + il * LAT_BIN_DEG)
    lat2 = np.radians(-90.0 + (il + 1) * LAT_BIN_DEG)
    return (r2**3 - r1**3) / 3.0 * math.radians(RA_BIN_DEG) * (np.sin(lat2) - np.sin(lat1))


def build_density(orb: OrbitSet, n_days: int = 30, k: int = 8, seed: int = 0) -> DensityGrid:
    """Weighted histogram over snapshots d=1..n_days (state at the middle of day d, t=(d-0.5) days)."""
    rng = np.random.default_rng(seed)
    keys_l, w_l, v_l, v2_l = [], [], [], []
    for d in range(1, n_days + 1):
        pos, vel, w = positions_at(orb, (d - 0.5) * 86400.0, k, rng)
        if len(pos) == 0:
            continue
        flat, ok = cell_indices(pos)
        key = (d - 1) * CELLS_PER_SNAPSHOT + flat
        key, vel, w = key[ok], vel[ok], w[ok]
        keys_l.append(key)
        w_l.append(w)
        v_l.append(vel * w[:, None])
        v2_l.append(w * np.einsum("ij,ij->i", vel, vel))
    if not keys_l:
        return DensityGrid(np.zeros(0, np.int64), np.zeros(0), np.zeros((0, 3)), np.zeros(0), k)
    key, w, wv, wv2 = (np.concatenate(x) for x in (keys_l, w_l, v_l, v2_l))
    uniq, inv = np.unique(key, return_inverse=True)
    wsum = np.bincount(inv, weights=w, minlength=len(uniq))
    vsum = np.stack([np.bincount(inv, weights=wv[:, c], minlength=len(uniq)) for c in range(3)], axis=1)
    v2sum = np.bincount(inv, weights=wv2, minlength=len(uniq))
    return DensityGrid(uniq.astype(np.int64), wsum, vsum, v2sum, k)


def lookup(grid: DensityGrid, day: np.ndarray, pos: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Density (objects/km^3), mean fragment velocity (n,3), velocity spread (km/s) at pos for snapshot day (1-based)."""
    n = len(pos)
    rho, vbar, sig = np.zeros(n), np.zeros((n, 3)), np.zeros(n)
    if len(grid.keys) == 0 or n == 0:
        return rho, vbar, sig
    flat, ok = cell_indices(pos)
    key = (np.asarray(day, dtype=np.int64) - 1) * CELLS_PER_SNAPSHOT + flat
    idx = np.minimum(np.searchsorted(grid.keys, key), len(grid.keys) - 1)
    hit = ok & (grid.keys[idx] == key)
    ii = idx[hit]
    w = grid.wsum[ii]
    rho[hit] = w / grid.k_samples / cell_volume_km3(flat[hit])
    vb = grid.vsum[ii] / w[:, None]
    vbar[hit] = vb
    sig[hit] = np.sqrt(np.maximum(grid.v2sum[ii] / w - np.einsum("ij,ij->i", vb, vb), 0.0))
    return rho, vbar, sig
