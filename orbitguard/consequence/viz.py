"""Debris-cloud visualisation payload built from the consequence engine's own simulated fragments.

Same inputs and seed as ``event.assess`` (so the fragments are the ones behind the published counts). Unlike the
exposure model, which places fragments at random mean anomalies (phase-mixed), this keeps each fragment's real
initial anomaly at the collision point, so the stream along the orbit is visible. Propagation is the model's:
two-body + J2 secular rates (RAAN, argument of perigee), no drag. Positions are model output, not tracked debris.
Frame: SGP4 TEME treated as inertial ECI, kilometres.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
from sgp4.api import SatrecArray

from orbitguard.catalog.catalog import MU_KM3_S2 as MU, RE_KM as RE, CatalogRecord
from orbitguard.catalog.propagate import J2, jd_fr, make_satrec

from .breakup import generate_fragments
from .cloud import OrbitSet, build_density, j2_secular_rates, solve_kepler, to_orbits
from .event import Params, leo_sats, state_at
from .exposure import compute_exposure
from .objects import object_mass_kg

EPOCHS_H = [0, 1, 6, 24, 72, 168, 720]
MAX_SAMPLE = 1500
TOP_SATS = 150
NOTE = ("NASA standard breakup model; fragments propagated two-body + J2 secular, no drag. "
        "Positions are model output, not tracked debris.")


def _anomaly(orb: OrbitSet, pos: np.ndarray) -> np.ndarray:
    """Mean anomaly (rad) of each orbit at the position ``pos`` (n,3) on it."""
    x = np.einsum("ij,ij->i", pos, orb.p_hat)
    y = np.einsum("ij,ij->i", pos, orb.q_hat)
    b = np.sqrt(1.0 - orb.e**2)
    big_e = np.arctan2(y / (orb.a * b), x / orb.a + orb.e)
    return np.mod(big_e - orb.e * np.sin(big_e), 2.0 * math.pi)


def propagate(orb: OrbitSet, m0: np.ndarray, t_s: float, n_rad_s: np.ndarray | None = None) -> np.ndarray:
    """ECI positions (n,3) km after ``t_s`` seconds: mean anomaly advances at n, plane drifts by the J2 secular rates."""
    if len(orb.a) == 0:
        return np.zeros((0, 3))
    n = np.sqrt(MU / orb.a**3) if n_rad_s is None else n_rad_s
    raan_dot, argp_dot = j2_secular_rates(orb.a, orb.e, orb.w_hat[:, 2])
    dw, d_o = argp_dot * t_s, raan_dot * t_s
    c, s = np.cos(dw)[:, None], np.sin(dw)[:, None]
    p = c * orb.p_hat + s * orb.q_hat
    q = -s * orb.p_hat + c * orb.q_hat
    co, so = np.cos(d_o), np.sin(d_o)

    def rz(v: np.ndarray) -> np.ndarray:
        return np.stack([co * v[:, 0] - so * v[:, 1], so * v[:, 0] + co * v[:, 1], v[:, 2]], axis=1)

    p, q = rz(p), rz(q)
    big_e = solve_kepler(np.mod(m0 + n * t_s, 2.0 * math.pi), orb.e)
    b = np.sqrt(1.0 - orb.e**2)
    return (orb.a * (np.cos(big_e) - orb.e))[:, None] * p + (orb.a * b * np.sin(big_e))[:, None] * q


def _subset(orb: OrbitSet, idx: np.ndarray) -> OrbitSet:
    return OrbitSet(orb.a[idx], orb.e[idx], orb.p_hat[idx], orb.q_hat[idx], orb.w_hat[idx], orb.weight[idx], 0, 0, len(idx))


def _elements(orb: OrbitSet, m0: np.ndarray, n_rad_s: np.ndarray | None = None) -> dict:
    """Compact orbital elements so the client can animate between epochs with the same model."""
    out = {"a_km": np.round(orb.a, 1).tolist(), "e": np.round(orb.e, 6).tolist(), "m0_rad": np.round(m0, 5).tolist(),
           "p": np.round(orb.p_hat, 5).ravel().tolist(), "q": np.round(orb.q_hat, 5).ravel().tolist()}
    if n_rad_s is not None:
        out["n_rad_s"] = [float(f"{x:.9g}") for x in n_rad_s]
    return out


def _epoch_positions(orb: OrbitSet, m0: np.ndarray, n_rad_s: np.ndarray | None = None) -> list[list[int]]:
    return [np.rint(propagate(orb, m0, h * 3600.0, n_rad_s)).astype(int).ravel().tolist() for h in EPOCHS_H]


def debris_payload(primary: CatalogRecord, threat: CatalogRecord, tca: datetime, miss_km: float,
                   records: list[CatalogRecord], p: Params | None = None, workers: int = 1,
                   max_sample: int = MAX_SAMPLE, top_sats: int = TOP_SATS) -> dict:
    p = p or Params()
    r1, v1 = state_at(primary, tca)
    r2, v2 = state_at(threat, tca)
    rng = np.random.default_rng(p.seed)  # identical stream to event.assess, so identical fragments
    fr = generate_fragments(object_mass_kg(primary), object_mass_kg(threat), r1, v1, r2, v2, rng, p.max_fragments)
    n_in = len(fr.lc_m)
    if n_in == 0:
        raise ValueError("the breakup model produced no fragments for this event")
    # exposure exactly as assess() computes it (the weight array here is the engine's)
    orb_all = to_orbits(fr.pos_km, fr.vel_kms, fr.weight)
    grid = build_density(orb_all, p.n_days, p.k_anomalies, p.seed)
    sats = leo_sats(records, {primary.norad, threat.norad})
    e_s = compute_exposure(grid, sats, tca, n_days=p.n_days, phases=p.phases, r_km=p.r_km, workers=workers)
    # same orbits again, tagged with the originating fragment index (the weight slot carries it)
    orb = to_orbits(fr.pos_km, fr.vel_kms, np.arange(n_in, dtype=np.float64))
    src = orb.weight.astype(np.int64)
    n_surv = len(orb.a)
    if n_surv == 0:
        raise ValueError("no fragment survives re-entry screening for this event")
    pick = np.sort(np.random.default_rng(p.seed + 7919).choice(n_surv, size=min(max_sample, n_surv), replace=False))
    sub = _subset(orb, pick)
    m0 = _anomaly(sub, fr.pos_km[src[pick]])

    order = [int(i) for i in np.argsort(-e_s)[:top_sats] if e_s[i] > 0]
    sat_recs = [sats[i] for i in order]
    jd, fr_d = jd_fr(tca, np.array([h * 3600.0 for h in EPOCHS_H]))
    err, rr, vv = SatrecArray([make_satrec(*s.tle) for s in sat_recs]).sgp4(jd, fr_d) if sat_recs else (None, None, None)
    if sat_recs and not np.all(err == 0):
        raise RuntimeError("SGP4 failed for an exposed satellite within 30 days of the event")
    sat_pos = np.asarray(rr)  # (n_sat, n_epoch, 3) TEME km, exact SGP4
    sat_orb = to_orbits(sat_pos[:, 0, :], np.asarray(vv)[:, 0, :], np.arange(len(sat_recs), dtype=np.float64))
    if len(sat_orb.a) != len(sat_recs):
        raise RuntimeError("an exposed satellite has an unbound or sub-orbital state at the event time")
    sat_m0 = _anomaly(sat_orb, sat_pos[:, 0, :])
    # TLE mean motion (rad/s) keeps the animated phase close to SGP4 over days
    sat_n = np.array([float(s.line2[52:63]) * 2.0 * math.pi / 86400.0 for s in sat_recs])
    return {
        "epochs_h": EPOCHS_H,
        "frame": "TEME (inertial) km",
        "tca_utc": tca.isoformat(),
        "miss_km": float(miss_km),
        "collision_point_km": [int(round(float(x))) for x in fr.pos_km.mean(axis=0)],
        "primary": {"name": primary.name, "norad": primary.norad, "pos_km": [np.rint(r1).astype(int).tolist()]},
        "threat": {"name": threat.name, "norad": threat.norad},
        "n_fragments_total": int(round(fr.n_true)),
        "n_fragments_modelled": n_in,
        "n_fragments_surviving": n_surv,
        "n_sampled": int(len(pick)),
        "satellites_at_risk": int((e_s >= 1.0).sum()),
        "satellites_considered": len(sats),
        "fragments": {"pos_km": _epoch_positions(sub, m0), "elements": _elements(sub, m0)},
        "satellites": [{"name": s.name, "norad": s.norad, "exposure": float(f"{e_s[i]:.4g}"),
                        "pos_km": [np.rint(sat_pos[k, j]).astype(int).tolist() for j in range(len(EPOCHS_H))]}
                       for k, (s, i) in enumerate(zip(sat_recs, order))],
        "satellite_elements": _elements(sat_orb, sat_m0, sat_n),
        "constants": {"mu_km3_s2": MU, "re_km": RE, "j2": J2},
        "exposure_note": "exposure = expected encounters within 1 km over 30 days (engine's E_s); satellites at risk = E_s >= 1",
        "note": NOTE,
        "params": {"seed": p.seed, "max_fragments": p.max_fragments, "r_km": p.r_km, "n_days": p.n_days},
    }
