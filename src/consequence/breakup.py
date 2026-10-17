"""SBM-inspired fragment generator (NASA Standard Breakup Model, Johnson et al. 2001; simplified).

Kept from the SBM: catastrophic threshold 40 J/g, ejected mass M, N(Lc)=0.1 M^0.75 Lc^-1.71, and
log10(dv[m/s]) ~ N(0.9 chi + 2.9, 0.4) with chi = log10(A/M).
Simplified: chi ~ N(-0.6, 0.5) independent of size (the SBM A/M distribution is size dependent and bridged);
only fragments of 10 cm..1 m are generated (power law truncated at 1 m); isotropic ejection; no fragment
shapes, no mass bookkeeping beyond M.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CATASTROPHIC_J_PER_G = 40.0
LC_MIN_M, LC_MAX_M = 0.10, 1.0
POWER = 1.71
CHI_MEAN, CHI_SIGMA = -0.6, 0.5
DV_SIGMA_LOG10 = 0.4


@dataclass
class Fragments:
    pos_km: np.ndarray  # (n,3)
    vel_kms: np.ndarray  # (n,3)
    lc_m: np.ndarray
    chi: np.ndarray
    dv_mps: np.ndarray
    weight: float  # N_true / N_sampled (each sampled fragment stands for this many)
    n_true: float
    catastrophic: bool
    ejected_mass_kg: float


def is_catastrophic(m1_kg: float, m2_kg: float, v_rel_kms: float) -> bool:
    m_small, m_large = min(m1_kg, m2_kg), max(m1_kg, m2_kg)
    e_j_per_g = 0.5 * m_small * (v_rel_kms * 1000.0) ** 2 / (m_large * 1000.0)
    return e_j_per_g > CATASTROPHIC_J_PER_G


def ejected_mass_kg(m1_kg: float, m2_kg: float, v_rel_kms: float) -> float:
    if is_catastrophic(m1_kg, m2_kg, v_rel_kms):
        return m1_kg + m2_kg
    return min(m1_kg, m2_kg) * v_rel_kms**2


def n_fragments(mass_kg: float, lc_m: float = LC_MIN_M) -> float:
    """Cumulative number of fragments of characteristic length >= lc_m."""
    return 0.1 * mass_kg**0.75 * lc_m**-POWER


def sample_lengths(n: int, rng: np.random.Generator) -> np.ndarray:
    """Inverse-CDF sampling of the power law on [LC_MIN, LC_MAX]."""
    a, b = LC_MIN_M**-POWER, LC_MAX_M**-POWER
    u = rng.random(n)
    return (a - u * (a - b)) ** (-1.0 / POWER)


def generate_fragments(m1_kg: float, m2_kg: float, r1_km: np.ndarray, v1_kms: np.ndarray,
                       r2_km: np.ndarray, v2_kms: np.ndarray, rng: np.random.Generator,
                       max_fragments: int = 3000) -> Fragments:
    r1, v1, r2, v2 = (np.asarray(x, dtype=np.float64) for x in (r1_km, v1_kms, r2_km, v2_kms))
    v_rel = float(np.linalg.norm(v1 - v2))
    cat = is_catastrophic(m1_kg, m2_kg, v_rel)
    mass = ejected_mass_kg(m1_kg, m2_kg, v_rel)
    n_true = n_fragments(mass)
    n = int(min(round(n_true), max_fragments))
    weight = n_true / n if n > 0 else 0.0
    mtot = m1_kg + m2_kg
    r_cm = (m1_kg * r1 + m2_kg * r2) / mtot
    v_cm = (m1_kg * v1 + m2_kg * v2) / mtot  # momentum-weighted
    lc = sample_lengths(n, rng)
    chi = rng.normal(CHI_MEAN, CHI_SIGMA, n)
    dv_mps = 10.0 ** rng.normal(0.9 * chi + 2.9, DV_SIGMA_LOG10)
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    vel = v_cm[None, :] + d * (dv_mps[:, None] / 1000.0)
    pos = np.tile(r_cm, (n, 1))
    return Fragments(pos, vel, lc, chi, dv_mps, float(weight), float(n_true), cat, float(mass))
