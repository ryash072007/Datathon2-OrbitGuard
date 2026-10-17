"""Expected close encounters of active LEO satellites with the debris cloud.

E_s = sum over snapshots and phases of  rho * v_rel * pi R^2 * dt,  v_rel = sqrt(|v_sat - vbar_cell|^2 + sigma_cell^2)
The cell velocity spread sigma is added in quadrature because the mean velocity alone underestimates crossing-plane
speeds. Satellites are sampled at M SGP4 phases within each day (TLE error grows over 30 days: caveat).
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

import numpy as np
from sgp4.api import SatrecArray

from orbitguard.catalog.catalog import CatalogRecord
from orbitguard.catalog.parallel import map_tasks
from orbitguard.catalog.propagate import jd_fr, make_satrec

from .cloud import DensityGrid, lookup

EXPOSED_THRESHOLD = 0.01
CHUNK = 250


def _chunk(task: dict) -> np.ndarray:
    tles, grid, tca = task["tles"], task["grid"], task["tca"]
    n_days, m, r_km = task["n_days"], task["phases"], task["r_km"]
    out = np.zeros(len(tles))
    if len(grid.keys) == 0:
        return out
    # snapshot d covers [d-1, d) days; M phases at the centres of M equal sub-intervals
    frac = (np.arange(n_days)[:, None] + (np.arange(m)[None, :] + 0.5) / m).ravel()
    days = np.repeat(np.arange(1, n_days + 1), m)
    dt_s = 86400.0 / m
    jd, fr = jd_fr(tca, frac * 86400.0)
    sats = SatrecArray([make_satrec(a, b) for a, b in tles])
    e, r, v = sats.sgp4(jd, fr)
    r, v = np.asarray(r), np.asarray(v)
    for i in range(len(tles)):
        good = e[i] == 0
        if not good.any():
            continue
        rho, vbar, sig = lookup(grid, days[good], r[i][good])
        dv = v[i][good] - vbar
        vrel = np.sqrt(np.einsum("ij,ij->i", dv, dv) + sig**2)
        out[i] = float(np.sum(rho * vrel) * math.pi * r_km**2 * dt_s)
    return out


def compute_exposure(grid: DensityGrid, sats: list[CatalogRecord], tca: datetime, *, n_days: int = 30,
                     phases: int = 16, r_km: float = 1.0, workers: int = 1) -> np.ndarray:
    """Expected encounters per satellite (same order as ``sats``)."""
    if not sats:
        return np.zeros(0)
    tasks = [{"tles": [s.tle for s in sats[i:i + CHUNK]], "grid": grid, "tca": tca, "n_days": n_days,
              "phases": phases, "r_km": r_km} for i in range(0, len(sats), CHUNK)]
    return np.concatenate(map_tasks(_chunk, tasks, workers))


def summarise(sats: list[CatalogRecord], e_s: np.ndarray, top_n: int = 10) -> dict:
    exposed = e_s > EXPOSED_THRESHOLD
    order = np.argsort(-e_s)[:top_n]
    by_prefix = Counter((sats[i].name.split() or ["?"])[0] for i in np.nonzero(exposed)[0])
    return {
        "n_sats_considered": len(sats),
        "n_sats_any_exposure": int(exposed.sum()),
        "n_sats_ge1_encounter": int((e_s >= 1.0).sum()),
        "total_expected_encounters": float(e_s.sum()),
        "top_satellites": [{"name": sats[i].name, "norad": sats[i].norad, "expected_encounters": float(e_s[i])}
                           for i in order if e_s[i] > 0],
        "exposed_by_constellation": dict(by_prefix.most_common(10)),
    }
