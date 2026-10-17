"""Close-approach sweep, graph construction and super-spreader scoring (numpy/scipy only)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from sgp4.api import SatrecArray

from src.consequence.objects import DEBRIS, PAYLOAD, ROCKET_BODY, object_mass_kg, object_type
from src.screen.catalog import CatalogRecord, co_orbiting
from src.screen.parallel import map_tasks
from src.screen.propagate import jd_fr, make_satrec

LEO_PERIGEE_KM = 2000.0

V_MAX_KMS = 15.5   # max LEO relative speed (head-on at ~7.7 km/s each)
SUB_BLOCK = 64     # time steps propagated at once inside a worker (bounds memory)

_EMPTY = (np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0), np.zeros(0))


def select_nodes(records: list[CatalogRecord]) -> list[CatalogRecord]:
    """Active LEO payloads and rocket bodies plus every debris-group object (de-duplicated by NORAD, sorted)."""
    out = [r for r in records if (r.group == "active" and r.perigee_km < LEO_PERIGEE_KM
                                  and object_type(r) in (PAYLOAD, ROCKET_BODY)) or object_type(r) == DEBRIS]
    return sorted(out, key=lambda r: r.norad)


def sgp4_state_grid(tles: list[tuple[str, str]], t0: datetime, n_steps: int, step_s: float,
                    block: int = 500) -> tuple[np.ndarray, np.ndarray]:
    """TEME position (km) and velocity (km/s), each (N, n_steps, 3); NaN where SGP4 fails."""
    jd, fr = jd_fr(t0, np.arange(n_steps) * step_s)
    pos = np.empty((len(tles), n_steps, 3))
    vel = np.empty_like(pos)
    for i0 in range(0, len(tles), block):
        sats = SatrecArray([make_satrec(a, b) for a, b in tles[i0:i0 + block]])
        e, r, v = sats.sgp4(jd, fr)
        r, v = np.array(r), np.array(v)
        r[e != 0] = np.nan
        v[e != 0] = np.nan
        pos[i0:i0 + block], vel[i0:i0 + block] = r, v
    return pos, vel


def encounters_from_state(pos: np.ndarray, vel: np.ndarray, step_s: float, r_km: float, k0: int = 0,
                          v_max_kms: float = V_MAX_KMS):
    """Swept-volume coarse search + linear closest-approach refinement inside each step.

    ``pos``/``vel`` are (N, T, 3). Per step a cKDTree finds pairs within r + v_max*dt/2; for each candidate the
    relative state (d, v) gives tau* = clamp(-d.v/|v|^2, -dt/2, dt/2) and d_min = |d + v tau*|; kept if < r.
    Returns (keys, step_index, d_min_km, v_rel_kms) with keys = i*N + j (i < j), step_index = k0 + t.
    """
    n, n_t, _ = pos.shape
    half = step_s / 2.0
    rad = r_km + v_max_kms * half
    ks, ts, ds, vs = [], [], [], []
    for t in range(n_t):
        p, v = pos[:, t, :], vel[:, t, :]
        ok = np.flatnonzero(np.all(np.isfinite(p), axis=1) & np.all(np.isfinite(v), axis=1))
        if len(ok) < 2:
            continue
        pairs = cKDTree(p[ok]).query_pairs(rad, output_type="ndarray")
        if len(pairs) == 0:
            continue
        a, b = ok[pairs[:, 0]], ok[pairs[:, 1]]
        d, rv = p[b] - p[a], v[b] - v[a]
        vv = np.einsum("ij,ij->i", rv, rv)
        tau = np.clip(-np.einsum("ij,ij->i", d, rv) / np.where(vv > 0, vv, 1.0), -half, half)
        dmin = np.linalg.norm(d + rv * tau[:, None], axis=1)
        m = dmin < r_km
        if not m.any():
            continue
        a, b = a[m], b[m]
        ks.append(np.minimum(a, b).astype(np.int64) * n + np.maximum(a, b))
        ts.append(np.full(int(m.sum()), k0 + t, np.int64))
        ds.append(dmin[m])
        vs.append(np.sqrt(vv[m]))
    if not ks:
        return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0), np.zeros(0)
    return np.concatenate(ks), np.concatenate(ts), np.concatenate(ds), np.concatenate(vs)


def merge_encounters(parts: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]], n: int):
    """Merge per-step hits into encounters (consecutive steps of one pair = one encounter).

    Returns (i, j, n_encounters, min_km, max_v_kms) per pair (i < j).
    """
    parts = [p for p in parts if len(p[0])]
    if not parts:
        return _EMPTY
    key = np.concatenate([p[0] for p in parts])
    step = np.concatenate([p[1] for p in parts])
    dist = np.concatenate([p[2] for p in parts])
    vrel = np.concatenate([p[3] for p in parts])
    order = np.lexsort((step, key))
    key, step, dist, vrel = key[order], step[order], dist[order], vrel[order]
    new_pair = np.r_[True, key[1:] != key[:-1]]
    new_enc = new_pair | np.r_[True, (step[1:] - step[:-1]) > 1]
    first = np.flatnonzero(new_pair)
    enc = np.add.reduceat(new_enc.astype(np.int64), first)
    uk = key[first]
    return uk // n, uk % n, enc, np.minimum.reduceat(dist, first), np.maximum.reduceat(vrel, first)


def sweep_chunk(task: dict) -> dict:
    """Pool worker (module level, explicit args): propagate all nodes over one time chunk, find encounters."""
    tles = [tuple(t) for t in task["tles"]]
    t_chunk0 = datetime.fromisoformat(task["t0"])
    step_s, k0, n_steps = task["step_s"], task["k0"], task["n_steps"]
    parts = []
    t_prop = t_pairs = 0.0
    for s0 in range(0, n_steps, SUB_BLOCK):
        m = min(SUB_BLOCK, n_steps - s0)
        t = time.perf_counter()
        pos, vel = sgp4_state_grid(tles, t_chunk0 + timedelta(seconds=(k0 + s0) * step_s), m, step_s)
        t_prop += time.perf_counter() - t
        t = time.perf_counter()
        parts.append(encounters_from_state(pos, vel, step_s, task["r_km"], k0 + s0))
        t_pairs += time.perf_counter() - t
    return {"keys": np.concatenate([p[0] for p in parts]), "step": np.concatenate([p[1] for p in parts]),
            "dist": np.concatenate([p[2] for p in parts]), "vrel": np.concatenate([p[3] for p in parts]),
            "propagate_s": t_prop, "pairs_s": t_pairs}


def sweep(records: list[CatalogRecord], t0: datetime, hours: float, step_s: float = 10.0, r_km: float = 10.0,
          workers: int = 1, chunks: int | None = None) -> dict:
    """Catalogue-wide close-approach sweep, parallelised over time chunks."""
    n_steps = int(hours * 3600 / step_s)
    n_chunks = max(1, min(chunks or workers * 4, n_steps))
    bounds = np.linspace(0, n_steps, n_chunks + 1).astype(int)
    tles = [r.tle for r in records]
    tasks = [{"tles": tles, "t0": t0.isoformat(), "k0": int(a), "n_steps": int(b - a), "step_s": step_s,
              "r_km": r_km} for a, b in zip(bounds[:-1], bounds[1:]) if b > a]
    t = time.perf_counter()
    res = map_tasks(sweep_chunk, tasks, workers)
    wall = time.perf_counter() - t
    n = len(records)
    t = time.perf_counter()
    i, j, enc, mind, maxv = merge_encounters([(r["keys"], r["step"], r["dist"], r["vrel"]) for r in res], n)
    # docked/attached objects (e.g. ISS visiting vehicles) share an orbit permanently: not conjunctions
    keep = np.array([not co_orbiting(records[int(a)], records[int(b)]) for a, b in zip(i, j)], dtype=bool)
    n_co = int((~keep).sum())
    i, j, enc, mind, maxv = i[keep], j[keep], enc[keep], mind[keep], maxv[keep]
    return {"i": i, "j": j, "steps": enc, "encounters": enc, "min_km": mind, "max_v_kms": maxv, "n_steps": n_steps,
            "step_s": step_s,
            "timings": {"sweep_wall_s": wall, "merge_s": time.perf_counter() - t,
                        "propagate_cpu_s": sum(r["propagate_s"] for r in res),
                        "pairs_cpu_s": sum(r["pairs_s"] for r in res), "co_orbiting_dropped": n_co,
                        "workers": workers, "chunks": len(tasks)}}


def score_graph(records: list[CatalogRecord], i: np.ndarray, j: np.ndarray) -> dict:
    """Degree, weighted degree, components and the super-spreader score (arrays of length N)."""
    n = len(records)
    deg = np.bincount(i, minlength=n) + np.bincount(j, minlength=n)
    adj = coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n))
    n_comp, labels = connected_components(adj, directed=False)
    mass = np.array([object_mass_kg(r) for r in records])
    crit = np.array([r.crit for r in records])
    # Degree centrality = degree / (N - 1), times log10(mass) so a 420 t station does not swamp everything
    # (raw mass made the score a mass ranking), times shell-density criticality.
    raw = (deg / max(n - 1, 1)) * np.log10(np.maximum(mass, 1.0)) * crit
    score = raw / raw.max() if raw.size and raw.max() > 0 else raw
    return {"degree": deg, "n_components": int(n_comp), "labels": labels, "mass": mass, "crit": crit,
            "score": score}


def build_network(records: list[CatalogRecord], sw: dict, top: int = 300) -> dict:
    """JSON-serialisable summary: the top ``top`` nodes by score and the edges among them."""
    i, j, steps = sw["i"], sw["j"], sw["steps"]
    max_v = sw.get("max_v_kms", np.zeros(len(i)))
    n = len(records)
    sc = score_graph(records, i, j)
    wdeg = np.bincount(i, weights=steps, minlength=n) + np.bincount(j, weights=steps, minlength=n)
    order = np.argsort(-sc["score"], kind="stable")
    keep = order[:top]
    keep_set = {int(k) for k in keep}
    comp_sizes = np.bincount(sc["labels"]) if n else np.zeros(0, int)
    nodes = []
    for rank, k in enumerate(keep):
        r = records[int(k)]
        nodes.append({"rank": rank + 1, "norad": r.norad, "name": r.name, "type": object_type(r),
                      "group": r.group, "degree": int(sc["degree"][k]), "wdegree": float(wdeg[k]),
                      "mass_kg": float(sc["mass"][k]), "crit": float(sc["crit"][k]),
                      "score": float(sc["score"][k]), "component_size": int(comp_sizes[sc["labels"][k]]),
                      "perigee_km": float(r.perigee_km), "apogee_km": float(r.apogee_km),
                      "inclination_deg": float(r.line2[8:16])})
    edges = [{"a": records[int(a)].norad, "b": records[int(b)].norad, "steps": int(s), "encounters": int(s),
              "min_km": float(d), "max_v_kms": float(v)}
             for a, b, s, d, v in zip(i, j, steps, sw["min_km"], max_v) if int(a) in keep_set and int(b) in keep_set]
    top_by_type = {}
    types = np.array([object_type(r) for r in records])
    for ty in (PAYLOAD, ROCKET_BODY, DEBRIS):
        idx = np.flatnonzero(types == ty)
        idx = idx[np.argsort(-sc["score"][idx], kind="stable")][:5]
        top_by_type[ty] = [{"norad": records[int(k)].norad, "name": records[int(k)].name, "type": ty,
                            "degree": int(sc["degree"][k]), "score": float(sc["score"][k]),
                            "mass_kg": float(sc["mass"][k])} for k in idx]
    return {"nodes": nodes, "edges": edges, "top_by_type": top_by_type,
            "summary": {"n_objects": n, "n_edges": int(len(i)), "n_components": sc["n_components"],
                        "largest_component": int(comp_sizes.max()) if len(comp_sizes) else 0,
                        "n_isolated": int((sc["degree"] == 0).sum()), "n_steps": sw["n_steps"], "step_s": sw.get("step_s")}}
