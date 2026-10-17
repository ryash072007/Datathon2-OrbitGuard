"""Independent encounter-plane Gaussian integration for circular hard bodies.

This is the short-encounter, rectilinear relative-motion approximation. It is
not applicable to slow co-orbital encounters or a long-duration collision risk.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
from scipy.integrate import IntegrationWarning, quad
from scipy.special import ndtr


def _vector(value, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3,) or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain three finite SI values")
    return arr


def _covariance(value, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3, 3) or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be a finite 3 by 3 position covariance")
    if not np.allclose(arr, arr.T, rtol=1e-10, atol=1e-10):
        raise ValueError(f"{name} must be symmetric")
    arr = (arr + arr.T) / 2
    if np.linalg.eigvalsh(arr)[0] <= 0:
        raise ValueError(f"{name} must be positive definite; no silent remediation")
    return arr


def encounter_plane(relative_velocity_mps) -> np.ndarray:
    velocity = _vector(relative_velocity_mps, "relative velocity")
    speed = np.linalg.norm(velocity)
    # Reference cases include very slow (0.014 m/s) GEO conjunctions. The
    # caller must additionally assess rectilinear applicability; reject a
    # genuinely undefined encounter plane here.
    if speed < 1e-6:
        raise ValueError("Unsupported near-zero relative velocity")
    normal = velocity / speed
    axis = np.zeros(3)
    axis[np.argmin(np.abs(normal))] = 1
    x = np.cross(normal, axis)
    x /= np.linalg.norm(x)
    y = np.cross(normal, x)
    return np.vstack((x, y))


def disk_probability(mean_m, covariance_m2, hard_body_radius_m: float) -> float:
    """Integrate a 2D normal over a disk, using one adaptive quadrature.

    The integration coordinates diagonalise the covariance. The inner
    Gaussian integral is analytic; complementary tails avoid cancellation.
    """
    mean = np.asarray(mean_m, dtype=float)
    cov = np.asarray(covariance_m2, dtype=float)
    radius = float(hard_body_radius_m)
    if mean.shape != (2,) or cov.shape != (2, 2):
        raise ValueError("Encounter-plane mean and covariance must be 2D")
    if not np.all(np.isfinite(mean)) or not np.all(np.isfinite(cov)):
        raise ValueError("Encounter-plane inputs must be finite")
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("Combined hard-body radius must be positive and finite")
    if not np.allclose(cov, cov.T, rtol=1e-10, atol=1e-10):
        raise ValueError("Encounter-plane covariance must be symmetric")
    values, vectors = np.linalg.eigh((cov + cov.T) / 2)
    if values[0] <= 0:
        raise ValueError("Encounter-plane covariance must be positive definite")
    # Integrate the narrower dimension analytically to reduce quadrature
    # difficulty for extremely anisotropic ellipses.
    mean = vectors.T @ mean
    sy, sx = np.sqrt(values)
    my, mx = mean
    normalization = radius / (math.sqrt(2 * math.pi) * sx)

    def integrand(u):
        x = radius * u
        ymax = radius * math.sqrt(max(0.0, 1 - u * u))
        lower = (-ymax - my) / sy
        upper = (ymax - my) / sy
        inner = (ndtr(-lower) - ndtr(-upper)) if lower > 0 else (ndtr(upper) - ndtr(lower))
        return normalization * math.exp(-0.5 * ((x - mx) / sx) ** 2) * inner

    with warnings.catch_warnings():
        warnings.simplefilter("error", IntegrationWarning)
        try:
            result, error = quad(integrand, -1, 1, epsabs=1e-13, epsrel=1e-8, limit=150)
        except IntegrationWarning as exc:
            raise ValueError(f"Collision-probability quadrature failed: {exc}") from exc
    if not math.isfinite(result) or error > max(1e-11, result * 1e-5):
        raise ValueError("Collision-probability quadrature did not converge")
    return float(np.clip(result, 0, 1))


def collision_probability(r1_m, v1_mps, cov1_m2, r2_m, v2_mps, cov2_m2,
                          hard_body_radius_m: float) -> float:
    """Return single-encounter probability under independent position errors."""
    r1, r2 = _vector(r1_m, "r1"), _vector(r2_m, "r2")
    v1, v2 = _vector(v1_mps, "v1"), _vector(v2_mps, "v2")
    c1, c2 = _covariance(cov1_m2, "cov1"), _covariance(cov2_m2, "cov2")
    plane = encounter_plane(v2 - v1)
    return disk_probability(plane @ (r2 - r1), plane @ (c1 + c2) @ plane.T,
                            hard_body_radius_m)


def rtn_covariance(state, sigma_rtn_m, scale: float = 1.0) -> np.ndarray:
    """Prescribed local-frame covariance at the encounter, not propagated OD."""
    state = np.asarray(state, dtype=float)
    radial = state[:3] / np.linalg.norm(state[:3])
    normal = np.cross(state[:3], state[3:])
    normal /= np.linalg.norm(normal)
    transverse = np.cross(normal, radial)
    rotation = np.column_stack((radial, transverse, normal))
    return rotation @ np.diag((np.asarray(sigma_rtn_m) * scale) ** 2) @ rotation.T

