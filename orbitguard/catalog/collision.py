"""Collision probability for real catalogue encounters.

Bridges the two halves of the project: SGP4 states from the CelesTrak screener go into the
encounter-plane Gaussian integral in ``orbitguard.physics.risk``, which reproduces the NASA CARA reference
cases to a relative error of 3e-6. The same uncertainty sweep and acceptance rule as the synthetic planner
apply here: a candidate is acceptable only if every evaluated encounter stays at or below the threshold at
0.5x, 1x and 2x the prescribed position error.

Public TLEs come without covariance, so the per-object position error is an ASSUMPTION (radial, along-track,
cross-track 1-sigma). Along-track error dominates for TLEs, hence the 2:1 ratio. Results are a screening
aid, not an operational Pc.
"""
from __future__ import annotations

import numpy as np

from orbitguard.physics.risk import collision_probability, rtn_covariance

TLE_SIGMA_RTN_M = (500.0, 1000.0, 500.0)
HBR_M = 20.0  # combined hard-body radius
UNCERTAINTY_SCALES = (0.5, 1.0, 2.0)
PC_THRESHOLD = 1e-4  # per-encounter acceptance threshold, as in the synthetic planner


def _cov(state_m, sigma_rtn_m, scale: float) -> np.ndarray:
    # R diag(s^2) R^T is symmetric only up to round-off (~1e-10 m^2 at km-scale sigmas), which the strict
    # input check in physics.risk would reject; symmetrise explicitly.
    c = rtn_covariance(state_m, sigma_rtn_m, scale)
    return (c + c.T) / 2.0


def encounter_pc(r1_km, v1_kms, r2_km, v2_kms, *, sigma_rtn_m=TLE_SIGMA_RTN_M, hbr_m: float = HBR_M,
                 scales=UNCERTAINTY_SCALES) -> dict:
    """Pc of one encounter at each uncertainty scale. Inputs are TEME/ECI states in km and km/s.

    Returns ``pc`` (1x scale), ``pc_worst`` (max over scales), ``by_scale`` and ``miss_km``, the miss distance
    in the encounter plane (the rectilinear closest approach, independent of the sampling instant).
    Raises ValueError for encounters the short-encounter model does not support (near-zero relative speed).
    """
    s1 = np.r_[np.asarray(r1_km, float), np.asarray(v1_kms, float)] * 1000.0
    s2 = np.r_[np.asarray(r2_km, float), np.asarray(v2_kms, float)] * 1000.0
    by_scale = {}
    for k in scales:
        by_scale[str(k)] = collision_probability(s1[:3], s1[3:], _cov(s1, sigma_rtn_m, k),
                                                 s2[:3], s2[3:], _cov(s2, sigma_rtn_m, k), hbr_m)
    rel, rv = s2[:3] - s1[:3], s2[3:] - s1[3:]
    miss_m = float(np.linalg.norm(rel - (rel @ rv) / (rv @ rv) * rv))
    return {"pc": by_scale.get("1.0", max(by_scale.values())), "pc_worst": max(by_scale.values()),
            "by_scale": by_scale, "miss_km": miss_m / 1000.0}
