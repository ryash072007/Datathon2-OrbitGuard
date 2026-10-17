"""Collision probability and expected harm.

Public TLEs have roughly 1 km position error and no covariance, so ``sigma_km`` is an ASSUMPTION the user can
change (default 1 km, isotropic in the encounter plane); the result is an order-of-magnitude indicator only.
The event assessment itself uses the full encounter-plane model in ``orbitguard.catalog.collision``.
"""
from __future__ import annotations

import numpy as np

from orbitguard.physics.risk import disk_probability


def pc_isotropic(miss_km: float, sigma_km: float = 1.0, hbr_m: float = 20.0) -> float:
    """Isotropic 2D Pc for a combined hard-body radius HBR, integrated exactly over the disk.

    Uses the NASA-validated quadrature from ``orbitguard.physics.risk`` instead of the small-HBR
    approximation HBR^2/(2 sigma^2) * exp(-d^2/(2 sigma^2)), which it matches when HBR << sigma.
    """
    if sigma_km <= 0:
        raise ValueError("sigma_km must be > 0")
    s_m = sigma_km * 1000.0
    return disk_probability([miss_km * 1000.0, 0.0], np.diag([s_m**2, s_m**2]), hbr_m)


def expected_harm(pc: float, total_expected_encounters: float) -> float:
    """Pc x total expected close encounters (continuous; a satellite count would saturate)."""
    return pc * total_expected_encounters
