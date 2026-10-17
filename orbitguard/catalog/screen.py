"""Cascade-aware manoeuvre screener.

For each candidate burn the primary's trajectory is manoeuvred by delta propagation (see
``propagate.py``), screened against the whole catalogue, and scored:

* ``miss_km_threat``    minimum distance to the threat object within +-5 min of the TCA (1 s sampling)
* ``new_conjunctions``  non-threat objects that come within ``r_km`` after the burn but did NOT in the
                        no-burn baseline (matched per object, not per event time)
* ``crit_penalty``      sum of those objects' criticality proxy (shell density, see ``catalog.py``)
* ``score``             dv_mps + lam * crit_penalty   (lam in m/s per unit criticality)
* ``feasible``          miss_km_threat >= target_km. The default 2 km reflects that TLE position error is
                        about 1 km (and no covariance is modelled), so a smaller miss is not trustworthy.

Rank: feasible first, then lowest score.

Pipeline: apogee/perigee prefilter (+-50 km) -> catalogue ephemeris computed ONCE on a 60 s grid and stored as
an explicit '<f8' np.memmap (workers re-open it, nothing big is pickled) -> coarse screen (distance <
R + v_rel*dt/2 on the grid) -> dense 1 s SGP4 refinement of each flagged window.
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .burns import Burn
from .catalog import CatalogRecord, co_orbiting, compute_criticality, data_dir, record_from_tle
from .parallel import map_tasks
from .propagate import (as_utc, delta_on_grid, jd_fr, make_satrec, open_ephemeris, sgp4_grid, sgp4_track,
                        write_ephemeris_memmap)

GRID_S = 60  # coarse grid step (seconds)
BAND_KM = 50.0  # apogee/perigee prefilter margin
POST_TCA_S = 12 * 3600
THREAT_HALF_WINDOW_S = 300  # miss distance is the minimum within +-5 min of the TCA
COLUMNS = ["burn_id", "direction", "dv_mps", "burn_time_utc", "miss_km_threat", "new_conjunctions",
           "crit_penalty", "score", "feasible", "lead_periods", "analytic_seed"]


# --------------------------------------------------------------------------- core scan

def _runs(flag_row: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate([[0], flag_row.astype(np.int8), [0]])
    d = np.diff(padded)
    return list(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))


def _refine(sat, jd1, fr1, prim1, ka: int, kb: int) -> tuple[float, int]:
    """Min distance (km) and its index on the 1 s grid for grid samples ka..kb (dense 1 s SGP4)."""
    a1, b1 = ka * GRID_S, kb * GRID_S
    e, r, _ = sat.sgp4_array(jd1[a1:b1 + 1], fr1[a1:b1 + 1])
    dist = np.linalg.norm(r - prim1[a1:b1 + 1], axis=1)
    dist[e != 0] = np.inf
    dist[np.isnan(dist)] = np.inf
    j = int(np.argmin(dist))
    return float(dist[j]), a1 + j


def scan(eph, prim60: np.ndarray, prim1: np.ndarray, jd1: np.ndarray, fr1: np.ndarray, sat_of,
         k_start: int, r_km: float, force_best: bool = False, block: int = 16) -> dict[int, tuple[float, int]]:
    """Coarse + dense screen of ``eph`` (N,T,3 on the 60 s grid) against the primary from grid index k_start.

    Returns {object index: (min distance km, index on the 1 s grid)} for objects that get within ``r_km``
    (plus the single closest coarse cell if ``force_best``, whatever its distance).
    """
    n, T, _ = eph.shape
    res: dict[int, tuple[float, int]] = {}
    forced = None
    for i0 in range(0, n, block):
        rel = np.asarray(eph[i0:i0 + block, k_start:, :]) - prim60[None, k_start:, :]
        with np.errstate(invalid="ignore"):
            d = np.sqrt((rel * rel).sum(-1))
            seg_v = np.sqrt((np.diff(rel, axis=1) ** 2).sum(-1)) / GRID_S
            # true min over a segment <= min(endpoint) ; allow v_rel*dt/2 (x1.2 for estimate error)
            flag = np.minimum(d[:, :-1], d[:, 1:]) < r_km + 1.2 * seg_v * GRID_S / 2.0
        if force_best and d.size:
            dd = np.where(np.isnan(d), np.inf, d)
            j = np.unravel_index(np.argmin(dd), dd.shape)
            if forced is None or dd[j] < forced[0]:
                forced = (float(dd[j]), i0 + int(j[0]), k_start + int(j[1]))
        for ri in np.nonzero(flag.any(axis=1))[0]:
            idx = i0 + int(ri)
            sat = sat_of(idx)
            for s, e in _runs(flag[ri]):
                dist, t1 = _refine(sat, jd1, fr1, prim1, k_start + s, k_start + e)
                if dist < r_km and (idx not in res or dist < res[idx][0]):
                    res[idx] = (dist, t1)
    if forced is not None and math.isfinite(forced[0]):
        _, idx, k = forced
        dist, t1 = _refine(sat_of(idx), jd1, fr1, prim1, max(k - 1, 0), min(k + 1, T - 1))
        if idx not in res or dist < res[idx][0]:
            res[idx] = (dist, t1)
    return res


# --------------------------------------------------------------------------- worker

def _threat_window(t0: datetime, tca: datetime, n_steps: int) -> tuple[int, int]:
    last = GRID_S * (n_steps - 1)
    c = int(round((tca - t0).total_seconds()))
    return max(0, c - THREAT_HALF_WINDOW_S), min(last, c + THREAT_HALF_WINDOW_S)


def _screen_chunk(task: dict) -> list[dict]:
    """Worker: screen a list of burns. Takes one explicit dict argument, builds everything it needs itself."""
    t0: datetime = task["t0"]
    n_steps: int = task["n_steps"]
    tles: list[tuple[str, str]] = task["tles"]
    r_km: float = task["r_km"]
    threat_idx: int = task["threat_idx"]
    base_close = set(task["base_close"])
    crit = task["crit"]

    off1 = np.arange(GRID_S * (n_steps - 1) + 1, dtype=np.float64)
    jd1, fr1 = jd_fr(t0, off1)
    r1, v1 = sgp4_track(make_satrec(*task["primary_tle"]), t0, off1)
    if np.isnan(r1).any():
        raise RuntimeError("SGP4 failed for the primary over the screening horizon")
    eph = open_ephemeris(Path(task["ephem_path"]), len(tles), n_steps)
    sats: dict[int, object] = {}

    def sat_of(i: int):
        if i not in sats:
            sats[i] = make_satrec(*tles[i])
        return sats[i]

    lo, hi = _threat_window(t0, task["tca"], n_steps)
    e, thr_r, _ = sat_of(threat_idx).sgp4_array(jd1[lo:hi + 1], fr1[lo:hi + 1])
    if (e != 0).any():
        raise RuntimeError("SGP4 failed for the threat near TCA")
    grid_off = np.arange(n_steps) * float(GRID_S)

    groups: dict[int, list[Burn]] = {}
    for b in task["burns"]:
        kb = int(round((b.burn_time - t0).total_seconds() / GRID_S))
        groups.setdefault(min(max(kb, 0), n_steps - 2), []).append(b)

    rows: list[dict] = []
    for kb, bs in groups.items():
        moving = [b for b in bs if b.dv_mps > 0]
        deltas = None
        if moving:
            deltas = delta_on_grid(r1[kb * GRID_S], v1[kb * GRID_S], np.array([b.dv_rtn_kms() for b in moving]),
                                   kb, n_steps, GRID_S)
        for b in bs:
            if b.dv_mps > 0:
                dl = deltas[moving.index(b)]
                prim1 = r1 + np.stack([np.interp(off1, grid_off, dl[:, c]) for c in range(3)], axis=1)
            else:
                prim1 = r1
            events = scan(eph, prim1[::GRID_S], prim1, jd1, fr1, sat_of, kb, r_km)
            miss = float(np.linalg.norm(thr_r - prim1[lo:hi + 1], axis=1).min())
            new = [i for i in events if i != threat_idx and i not in base_close]
            penalty = float(sum(crit[i] for i in new))
            rows.append({
                "burn_id": b.burn_id, "direction": b.direction, "dv_mps": b.dv_mps,
                "burn_time_utc": (t0 + timedelta(seconds=kb * GRID_S)).isoformat(),
                "miss_km_threat": miss, "new_conjunctions": len(new), "crit_penalty": penalty,
                "lead_periods": b.lead_periods, "analytic_seed": b.analytic_seed,
                "_events": sorted(events),
            })
    return rows


# --------------------------------------------------------------------------- context / public API

@dataclass
class ScreenContext:
    primary_tle: tuple[str, str]
    tles: list[tuple[str, str]]
    norads: list[int]
    names: list[str]
    crit: list[float]
    t0: datetime
    n_steps: int
    tca: datetime
    ephem_path: Path
    threat_idx: int
    base_close: list[int]
    baseline_miss_km: float
    r_km: float
    target_km: float
    lam: float
    timings: dict = field(default_factory=dict)

    @property
    def threat_name(self) -> str:
        return self.names[self.threat_idx]

    @property
    def threat_norad(self) -> int:
        return self.norads[self.threat_idx]


def _as_record(item) -> tuple[CatalogRecord, bool]:
    if isinstance(item, CatalogRecord):
        return item, True
    l1, l2 = item
    return record_from_tle(f"NORAD {int(l1[2:7])}", l1, l2, ""), False


def prepare(primary_tle: tuple[str, str], catalog: list, tca: datetime, burns: list[Burn], *,
            target_km: float = 2.0, lam: float = 0.05, r_km: float = 5.0, cache_dir: Path | None = None,
            threat_norad: int | None = None) -> ScreenContext:
    """Prefilter, build the shared ephemeris memmap, pick the threat and compute the no-burn baseline."""
    timings: dict[str, float] = {}
    tca = as_utc(tca)
    cache_dir = cache_dir or data_dir() / "cache"
    prim = record_from_tle("PRIMARY", *primary_tle)

    t = time.perf_counter()
    pairs = [_as_record(c) for c in catalog]
    records = [p[0] for p in pairs]
    if not all(p[1] for p in pairs):  # bare TLE tuples: compute the criticality proxy ourselves
        compute_criticality(records)
    sel = [r for r in records if r.norad != prim.norad and not co_orbiting(prim, r)
           and r.perigee_km <= prim.apogee_km + BAND_KM and r.apogee_km >= prim.perigee_km - BAND_KM]
    if threat_norad is not None and not any(r.norad == threat_norad for r in sel):
        extra = [r for r in records if r.norad == threat_norad]
        if not extra:
            raise ValueError(f"threat NORAD {threat_norad} not in the catalogue")
        sel += extra
    if not sel:
        raise ValueError("no catalogue objects survive the apogee/perigee prefilter")
    timings["prefilter_s"] = time.perf_counter() - t
    timings["n_catalog"] = len(records)
    timings["n_after_prefilter"] = len(sel)

    movers = [b.burn_time for b in burns if b.dv_mps > 0]
    t0 = as_utc(min(movers) if movers else tca - timedelta(minutes=30)).replace(microsecond=0)
    n_steps = int(math.ceil((tca + timedelta(seconds=POST_TCA_S) - t0).total_seconds() / GRID_S)) + 1
    tles = [r.tle for r in sel]

    t = time.perf_counter()
    key = hashlib.sha1(("|".join(a + b for a, b in tles) + t0.isoformat() + str(n_steps)).encode()).hexdigest()[:12]
    path = cache_dir / f"ephem_{key}.f8"
    expected = len(tles) * n_steps * 3 * 8
    if not (path.exists() and path.stat().st_size == expected):
        write_ephemeris_memmap(tles, t0, n_steps, path, GRID_S)
    timings["ephemeris_s"] = time.perf_counter() - t

    # threat: object closest to the primary near TCA (or the explicit one)
    t = time.perf_counter()
    eph = open_ephemeris(path, len(tles), n_steps)
    kt = int(round((tca - t0).total_seconds() / GRID_S))
    ks = np.arange(max(kt - 3, 0), min(kt + 3, n_steps - 1) + 1)
    prim_sat = make_satrec(*primary_tle)
    pk, _ = sgp4_track(prim_sat, t0, ks * float(GRID_S))
    with np.errstate(invalid="ignore"):
        dk = np.linalg.norm(np.asarray(eph[:, ks, :]) - pk[None], axis=-1)
    dk = np.where(np.isnan(dk), np.inf, dk).min(axis=1)
    if threat_norad is not None:
        cands = [i for i, r in enumerate(sel) if r.norad == threat_norad]
    else:
        cands = np.argsort(dk)[:5].tolist()
    lo, hi = _threat_window(t0, tca, n_steps)
    off = np.arange(lo, hi + 1, dtype=np.float64)
    rp, _ = sgp4_track(prim_sat, t0, off)
    best = (math.inf, cands[0])
    for i in cands:
        ro, _ = sgp4_track(make_satrec(*tles[i]), t0, off)
        m = float(np.nanmin(np.linalg.norm(ro - rp, axis=1)))
        best = min(best, (m, i))
    threat_idx = best[1]

    ctx = ScreenContext(primary_tle, tles, [r.norad for r in sel], [r.name for r in sel],
                        [r.crit for r in sel], t0, n_steps, tca, path, threat_idx, [], best[0],
                        r_km, target_km, lam, timings)
    base = _screen_chunk(_task(ctx, [Burn("none", "none", 0.0, t0, 0.0)]))[0]
    ctx.base_close = base["_events"]
    ctx.baseline_miss_km = base["miss_km_threat"]
    timings["baseline_s"] = time.perf_counter() - t
    return ctx


def _task(ctx: ScreenContext, burns: list[Burn]) -> dict:
    return {"primary_tle": ctx.primary_tle, "tles": ctx.tles, "crit": ctx.crit, "t0": ctx.t0,
            "n_steps": ctx.n_steps, "tca": ctx.tca, "ephem_path": str(ctx.ephem_path),
            "threat_idx": ctx.threat_idx, "base_close": ctx.base_close, "r_km": ctx.r_km, "burns": burns}


def run_burns(ctx: ScreenContext, burns: list[Burn], workers: int = 1) -> "pd.DataFrame":
    """Screen ``burns`` (split across ``workers`` processes) and return the ranked DataFrame."""
    import pandas as pd  # local import: keeps spawned workers light (they only need numpy + sgp4)

    t = time.perf_counter()
    groups: dict[int, list[Burn]] = {}
    for b in burns:
        kb = int(round((b.burn_time - ctx.t0).total_seconds() / GRID_S))
        groups.setdefault(kb, []).append(b)
    pieces = max(1, math.ceil(workers / len(groups)))
    tasks = [_task(ctx, bs[p::pieces]) for bs in groups.values() for p in range(pieces) if bs[p::pieces]]
    rows = [r for chunk in map_tasks(_screen_chunk, tasks, workers) for r in chunk]
    df = pd.DataFrame(rows).drop(columns="_events")
    df["score"] = df["dv_mps"] + ctx.lam * df["crit_penalty"]
    df["feasible"] = df["miss_km_threat"] >= ctx.target_km
    df = (df[COLUMNS].assign(_nf=~df["feasible"], _m=-df["miss_km_threat"])
          .sort_values(["_nf", "score", "_m"]).drop(columns=["_nf", "_m"]).reset_index(drop=True))
    df.attrs["timings"] = dict(ctx.timings, burns_s=time.perf_counter() - t, workers=workers)
    df.attrs["threat"] = {"name": ctx.threat_name, "norad": ctx.threat_norad}
    df.attrs["baseline_miss_km"] = ctx.baseline_miss_km
    return df


def screen(primary_tle: tuple[str, str], catalog: list, tca: datetime, burns: list[Burn], *,
           target_km: float = 2.0, lam: float = 0.05, r_km: float = 5.0, workers: int = 1,
           cache_dir: Path | None = None, threat_norad: int | None = None) -> "pd.DataFrame":
    """Interface function. ``catalog`` is a list of (line1, line2) tuples or CatalogRecord objects."""
    ctx = prepare(primary_tle, catalog, tca, burns, target_km=target_km, lam=lam, r_km=r_km,
                  cache_dir=cache_dir, threat_norad=threat_norad)
    return run_burns(ctx, burns, workers)


# --------------------------------------------------------------------------- closest-approach search

def find_approach(primary: CatalogRecord, records: list[CatalogRecord], t_start: datetime, days: float,
                  r_km: float = 50.0, only_norad: int | None = None, chunk_h: float = 6.0) -> dict:
    """Closest approach of ``primary`` to any (prefiltered) catalogue object in [t_start, t_start+days]."""
    t_start = as_utc(t_start)
    if only_norad is not None:
        cand = [r for r in records if r.norad == only_norad]
        if not cand:
            raise ValueError(f"NORAD {only_norad} not in the catalogue")
    else:
        cand = [r for r in records if r.norad != primary.norad and not co_orbiting(primary, r)
                and r.perigee_km <= primary.apogee_km + BAND_KM and r.apogee_km >= primary.perigee_km - BAND_KM]
    tles = [r.tle for r in cand]
    sats: dict[int, object] = {}

    def sat_of(i: int):
        if i not in sats:
            sats[i] = make_satrec(*tles[i])
        return sats[i]

    prim = make_satrec(*primary.tle)
    chunk_steps = int(chunk_h * 3600 / GRID_S)
    total_steps = int(days * 86400 / GRID_S)
    best = (math.inf, None, None)
    n_under = 0
    k = 0
    while k < total_steps:
        n_steps = min(chunk_steps, total_steps - k) + 3  # small overlap so no segment is lost at the seams
        tc = t_start + timedelta(seconds=k * GRID_S)
        eph = sgp4_grid(tles, tc, n_steps, GRID_S)
        off1 = np.arange(GRID_S * (n_steps - 1) + 1, dtype=np.float64)
        jd1, fr1 = jd_fr(tc, off1)
        r1, _ = sgp4_track(prim, tc, off1)
        res = scan(eph, r1[::GRID_S], r1, jd1, fr1, sat_of, 0, r_km, force_best=True)
        for idx, (d, i1) in res.items():
            n_under += d < r_km
            if d < best[0]:
                best = (d, idx, tc + timedelta(seconds=float(i1)))
        k += chunk_steps
    if best[1] is None:
        raise RuntimeError("no approach found (no valid SGP4 states)")
    return {"record": cand[best[1]], "tca": best[2], "miss_km": best[0], "n_under_r": int(n_under),
            "n_candidates": len(cand), "r_km": r_km}
