"""Positions for the 3D globe panel: debris-cloud snapshots, orbit tracks, best burn, exposed satellites.

Reuses the consequence engine's breakup and cloud code unchanged. Frame is SGP4's TEME (treated as inertial ECI),
so Earth is drawn static. Coordinates in km, rounded to 1 decimal.

Caveats stored in the payload: fragment anomalies are random (phase-mixed cloud), which is optimistic at 0.1 d
when the cloud is really still a compact shell near the collision point; the burn track is the burn's
displacement from the baseline orbit multiplied by ``burn_exaggeration`` so it is visible at globe scale.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from orbitguard.catalog.catalog import CatalogRecord, data_dir, period_min_from_tle
from orbitguard.catalog.propagate import make_satrec, maneuvered_positions, sgp4_track

from .breakup import generate_fragments
from .cloud import positions_at, to_orbits
from .event import Params, state_at

N_TRACK = 120
BURN_EXAGGERATION = 50.0
EARTH_RADIUS_KM = 6371.0


def _r1(a: np.ndarray) -> list:
    return np.round(np.asarray(a, dtype=np.float64), 1).tolist()


def _parse_t(s: str) -> datetime:
    t = datetime.fromisoformat(str(s))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def _track(rec: CatalogRecord, tca: datetime, n: int = N_TRACK) -> np.ndarray:
    """One orbit ending at TCA, n points."""
    period_s = period_min_from_tle(rec.line2) * 60.0
    t0 = tca - timedelta(seconds=period_s)
    r, _ = sgp4_track(make_satrec(*rec.tle), t0, np.linspace(0.0, period_s, n))
    return r[np.all(np.isfinite(r), axis=1)]


def _burn_track(rec: CatalogRecord, tca: datetime, burn: dict, n: int = N_TRACK) -> np.ndarray | None:
    from orbitguard.catalog.burns import DIRECTION_VECTORS
    d = burn.get("direction")
    if d not in DIRECTION_VECTORS or not burn.get("burn_time_utc"):
        return None
    t_b = _parse_t(burn["burn_time_utc"])
    if t_b >= tca:
        return None
    u = DIRECTION_VECTORS[d]
    dv = tuple(x * float(burn["dv_mps"]) / 1000.0 for x in u)
    period_s = period_min_from_tle(rec.line2) * 60.0
    n_grid = int((tca - t_b).total_seconds() // 60) + 1
    man, base = maneuvered_positions(make_satrec(*rec.tle), t_b, n_grid, 0, dv)
    k = min(n_grid, int(period_s // 60) + 1)  # last orbit before TCA
    man, base = man[-k:], base[-k:]
    out = base + BURN_EXAGGERATION * (man - base)
    idx = np.unique(np.linspace(0, k - 1, min(n, k)).round().astype(int))
    return out[idx]


def _latest_consequence_json(norad: int) -> dict | None:
    files = sorted((data_dir() / "out").glob(f"consequence_{norad}_*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def cloud_snapshots(event_facts: dict, days: tuple[float, ...] = (0.1, 1, 7, 30), n_points: int = 1500, *,
                    records: list[CatalogRecord] | None = None, seed: int = 0, write: bool = True) -> dict:
    """event_facts: the facts dict (needs event.primary/threat/tca_utc, consequence.fragments_true, burns.top)."""
    ev = event_facts["event"]
    p_id, t_id = int(ev["primary"]["norad"]), int(ev["threat"]["norad"])
    tca = _parse_t(ev["tca_utc"])
    if records is None:
        from orbitguard.catalog.catalog import load_catalog
        records = load_catalog()
    by_id = {r.norad: r for r in records}
    for i in (p_id, t_id):
        if i not in by_id:
            raise ValueError(f"NORAD {i} not in the catalogue")
    primary, threat = by_id[p_id], by_id[t_id]

    r1, v1 = state_at(primary, tca)
    r2, v2 = state_at(threat, tca)
    rng = np.random.default_rng(seed)
    fr = generate_fragments(float(ev["primary"]["mass_kg"]), float(ev["threat"]["mass_kg"]), r1, v1, r2, v2, rng,
                            Params().max_fragments)
    orb = to_orbits(fr.pos_km, fr.vel_kms, fr.weight)

    snaps = []
    for d in days:
        pos, _, _ = positions_at(orb, float(d) * 86400.0, 1, rng)
        if len(pos) > n_points:
            pos = pos[rng.choice(len(pos), n_points, replace=False)]
        snaps.append({"day": float(d), "n": int(len(pos)), "points": _r1(pos)})

    tracks = {"primary": _r1(_track(primary, tca)), "threat": _r1(_track(threat, tca))}
    best = ((event_facts.get("burns") or {}).get("top") or [None])[0]
    burn = None
    if best:
        bt = _burn_track(primary, tca, best)
        if bt is not None:
            burn = {"burn_id": best["burn_id"], "dv_mps": best["dv_mps"], "direction": best["direction"],
                    "exaggeration": BURN_EXAGGERATION, "points": _r1(bt)}

    sats = []
    cons = _latest_consequence_json(p_id)
    for s in ((cons or {}).get("top_satellites") or [])[:50]:
        rec = by_id.get(int(s.get("norad", -1)))
        if rec is None:
            continue
        try:
            sats.append({"name": rec.name, "norad": rec.norad, "xyz": _r1(state_at(rec, tca)[0])})
        except RuntimeError:
            continue

    n_true = float((event_facts.get("consequence") or {}).get("fragments_true") or fr.n_true)
    out = {"norad": p_id, "primary": ev["primary"]["name"], "threat": ev["threat"]["name"], "tca_utc": tca.isoformat(),
           "frame": "ECI (TEME, km)", "earth_radius_km": EARTH_RADIUS_KM, "fragments_true": n_true,
           "fragments_sampled": int(len(fr.lc_m)), "snapshots": snaps, "tracks": tracks, "burn": burn,
           "satellites": sats, "collision_point": _r1(0.5 * (r1 + r2)),
           "caveats": ["fragment anomalies are random (phase-mixed): optimistic dilution at 0.1 d",
                       f"burn track = displacement x{BURN_EXAGGERATION:g}"]}
    if write:
        path = Path(data_dir()) / "out" / f"globe_{p_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out
