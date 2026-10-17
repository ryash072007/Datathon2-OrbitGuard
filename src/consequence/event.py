"""One conjunction event end to end: states at TCA -> fragments -> cloud density -> exposure -> expected harm."""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

import numpy as np

from src.screen.catalog import CatalogRecord, period_min_from_tle
from src.screen.propagate import make_satrec, sgp4_track
from src.screen.screen import find_approach

from .breakup import generate_fragments
from .cloud import build_density, positions_at, to_orbits
from .exposure import compute_exposure, summarise
from .objects import ASSUMPTIONS, object_mass_kg, object_type
from .pc import expected_harm, pc_isotropic

LEO_PERIGEE_KM = 2000.0


@dataclass
class Params:
    seed: int = 0
    max_fragments: int = 3000
    k_anomalies: int = 8
    phases: int = 16
    n_days: int = 30
    r_km: float = 1.0
    sigma_km: float = 1.0
    hbr_m: float = 20.0


def leo_sats(records: list[CatalogRecord], exclude: set[int]) -> list[CatalogRecord]:
    return [r for r in records if r.group == "active" and r.perigee_km < LEO_PERIGEE_KM and r.norad not in exclude]


def state_at(rec: CatalogRecord, t: datetime) -> tuple[np.ndarray, np.ndarray]:
    r, v = sgp4_track(make_satrec(*rec.tle), t, np.array([0.0]))
    if not np.all(np.isfinite(r)):
        raise RuntimeError(f"SGP4 failed for {rec.name} at {t}")
    return r[0], v[0]


def assess(primary: CatalogRecord, threat: CatalogRecord, tca: datetime, miss_km: float,
           records: list[CatalogRecord], p: Params, workers: int = 1) -> dict:
    """Consequence assessment; ``workers`` parallelises the exposure stage over satellites."""
    tim: dict[str, float] = {}
    r1, v1 = state_at(primary, tca)
    r2, v2 = state_at(threat, tca)
    m1, m2 = object_mass_kg(primary), object_mass_kg(threat)
    rng = np.random.default_rng(p.seed)
    t = time.perf_counter()
    fr = generate_fragments(m1, m2, r1, v1, r2, v2, rng, p.max_fragments)
    tim["breakup_s"] = time.perf_counter() - t

    t = time.perf_counter()
    orb = to_orbits(fr.pos_km, fr.vel_kms, fr.weight)
    grid = build_density(orb, p.n_days, p.k_anomalies, p.seed)
    tim["cloud_s"] = time.perf_counter() - t

    # sanity: altitude distribution of fragments one day after the break-up
    parent_alt = float(np.linalg.norm(0.5 * (r1 + r2)) - 6378.137)
    pos_d1, _, _ = positions_at(orb, 0.5 * 86400.0, 1, np.random.default_rng(p.seed + 1))
    alt_d1 = np.linalg.norm(pos_d1, axis=1) - 6378.137 if len(pos_d1) else np.zeros(0)

    t = time.perf_counter()
    sats = leo_sats(records, {primary.norad, threat.norad})
    e_s = compute_exposure(grid, sats, tca, n_days=p.n_days, phases=p.phases, r_km=p.r_km, workers=workers)
    tim["exposure_s"] = time.perf_counter() - t
    summ = summarise(sats, e_s)

    pc = pc_isotropic(miss_km, p.sigma_km, p.hbr_m)
    n_surv = len(orb.a)
    return {
        "primary": {"name": primary.name, "norad": primary.norad, "type": object_type(primary), "mass_kg": m1},
        "threat": {"name": threat.name, "norad": threat.norad, "type": object_type(threat), "mass_kg": m2},
        "tca_utc": tca.isoformat(), "miss_km": float(miss_km),
        "v_rel_kms": float(np.linalg.norm(v1 - v2)), "parent_alt_km": parent_alt,
        "catastrophic": fr.catastrophic, "ejected_mass_kg": fr.ejected_mass_kg,
        "fragments_true": fr.n_true, "fragments_sampled": int(len(fr.lc_m)), "fragment_weight": fr.weight,
        "reentered_fraction": (orb.n_reentered / orb.n_input) if orb.n_input else 0.0,
        "unbound_fraction": (orb.n_unbound / orb.n_input) if orb.n_input else 0.0,
        "survivors_sampled": n_surv,
        "alt_day1_p10_p50_p90_km": [float(x) for x in np.percentile(alt_d1, [10, 50, 90])] if len(alt_d1) else [],
        "frac_within_100km_of_parent_alt_day1": float(np.mean(np.abs(alt_d1 - parent_alt) < 100.0)) if len(alt_d1) else 0.0,
        "pc": pc, "n_sats_any_exposure": summ["n_sats_any_exposure"], "n_sats_ge1_encounter": summ["n_sats_ge1_encounter"],
        "total_expected_encounters": summ["total_expected_encounters"],
        "expected_harm": expected_harm(pc, summ["total_expected_encounters"]),
        "top_satellites": summ["top_satellites"], "exposed_by_constellation": summ["exposed_by_constellation"],
        "n_sats_considered": summ["n_sats_considered"],
        "params": asdict(p), "timings": tim,
    }


def survey_task(task: dict) -> dict:
    """Pool worker (module level, explicit args): closest approach in the next days, then assess (serial exposure)."""
    primary: CatalogRecord = task["primary"]
    records: list[CatalogRecord] = task["records"]
    p: Params = task["params"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    t0 = time.perf_counter()
    found = find_approach(primary, records, now + timedelta(minutes=1), task["days"])
    t_find = time.perf_counter() - t0
    tca = found["tca"].replace(microsecond=0)
    p_i = Params(**{**asdict(p), "seed": p.seed + task["index"]})
    out = assess(primary, found["record"], tca, found["miss_km"], records, p_i, workers=1)
    out["timings"]["find_approach_s"] = t_find
    return out
