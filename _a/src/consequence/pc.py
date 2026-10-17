"""Collision probability and expected harm.

Public TLEs have roughly 1 km position error and no covariance, so ``sigma_km`` is an ASSUMPTION the user can
change (default 1 km, isotropic in the encounter plane); the result is an order-of-magnitude indicator only.
"""
from __future__ import annotations

import math


def pc_isotropic(miss_km: float, sigma_km: float = 1.0, hbr_m: float = 20.0) -> float:
    """Small-HBR isotropic 2D Pc = HBR^2/(2 sigma^2) * exp(-d^2/(2 sigma^2)); HBR = combined hard-body radius."""
    if sigma_km <= 0:
        raise ValueError("sigma_km must be > 0")
    hbr_km = hbr_m / 1000.0
    s2 = 2.0 * sigma_km**2
    return (hbr_km**2 / s2) * math.exp(-(miss_km**2) / s2)


def expected_harm(pc: float, total_expected_encounters: float) -> float:
    """Pc x total expected close encounters (continuous; a satellite count would saturate)."""
    return pc * total_expected_encounters
