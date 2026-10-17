"""Close-approach sweep, graph construction and super-spreader scoring (numpy/scipy only)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from src.consequence.objects import DEBRIS, PAYLOAD, object_mass_kg, object_type
from src.screen.catalog import CatalogRecord, co_orbiting
from src.screen.parallel import map_tasks
from src.screen.propagate import sgp4_grid

LEO_PERIGEE_KM = 2000.0

_EMPTY = (np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0))


def select_nodes(records: list[CatalogRecord]) -> list[CatalogRecord]:
    """Active LEO payloads plus every object from the debris groups (de-duplicated by NORAD, sorted)."""
    out = [r for r in records if (r.group == "active" and r.perigee_km < LEO_PERIGEE_KM
                                  and object_type(r) == PAYLOAD) or object_type(r) == DEBRIS]
    return sorted(out, key=lambda r: r.norad)


def merge_pairs(parts: list[tuple[np.ndarray, np.ndarray, np.ndarray]], n: int):
    """Merge (keys, counts, dist) parts -> (i, j, steps, min_km). Keys are i*n+j with i<j."""
    keys = np.concatenate([p[0] for p in parts]) if parts else np.zeros(0, np.int64)
    if len(keys) == 0:
        return _EMPTY
    cnt = np.concatenate([p[1] for p in parts])
    dist = np.concatenate([p[2] for p in parts])
    order = np.argsort(keys, kind="stable")
    keys, cnt, dist = keys[order], cnt[order], dist[order]
    first = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    steps = np.add.reduceat(cnt, first)
    mind = np.minimum.reduceat(dist, first)
    uk = keys[first]
    return uk // n, uk % n, steps, mind


def pairs_from_positions(pos: np.ndarray, r_km: float):
    """Close pairs over time. ``pos`` is (N, T, 3) km. One cKDTree per time step; NaN rows are skipped.

    Returns (i, j, steps, min_km) aggregated per pair (i < j).
    """
    n, n_t, _ = pos.shape
    keys: list[np.ndarray] = []
    dists: list[np.ndarray] = []
    for t in range(n_t):
        p = pos[:, t, :]
        ok = np.flatnonzero(np.all(np.isfinite(p), axis=1))
        if len(ok) < 2:
            continue
        pairs = cKDTree(p[ok]).query_pairs(r_km, output_type="ndarray")
        if len(pairs) == 0:
            continue
        a, b = ok[pairs[:, 0]], ok[pairs[:, 1]]
        lo, hi = np.minimum(a, b).astype(np.int64), np.maximum(a, b).astype(np.int64)
        keys.append(lo * n + hi)
        dists.append(np.linalg.norm(p[a] - p[b], axis=1))
    if not keys:
        return _EMPTY
    k = np.concatenate(keys)
    return merge_pairs([(k, np.ones(len(k), np.int64), np.concatenate(dists))], n)


def sweep_chunk(task: dict) -> dict:
    """Pool worker (module level, explicit args): propagate all nodes over one time chunk, find pairs."""
    tles = [tuple(t) for t in task["tles"]]
    t0 = datetime.fromisoformat(task["t0"]) + timedelta(seconds=task["k0"] * task["step_s"])
    t = time.perf_counter()
    pos = sgp4_grid(tles, t0, task["n_steps"], task["step_s"])
    t_prop = time.perf_counter() - t
    t = time.perf_counter()
    n = len(tles)
    i, j, steps, mind = pairs_from_positions(pos, task["r_km"])
    return {"keys": i * n + j, "steps": steps, "min_km": mind, "propagate_s": t_prop,
            "pairs_s": time.perf_counter() - t}


def sweep(records: list[CatalogRecord], t0: datetime, hours: float, step_s: float = 60.0, r_km: float = 10.0,
          workers: int = 1, chunks: int | None = None) -> dict:
    """Catalogue-wide close-approach sweep, parallelised over time chunks."""
    n_steps = int(hours * 3600 / step_s)
    n_chunks = max(1, min(chunks or workers * 2, n_steps))
    bounds = np.linspace(0, n_steps, n_chunks + 1).astype(int)
    tles = [r.tle for r in records]
    tasks = [{"tles": tles, "t0": t0.isoformat(), "k0": int(a), "n_steps": int(b - a), "step_s": step_s,
              "r_km": r_km} for a, b in zip(bounds[:-1], bounds[1:]) if b > a]
    t = time.perf_counter()
    res = map_tasks(sweep_chunk, tasks, workers)
    wall = time.perf_counter() - t
    n = len(records)
    t = time.perf_counter()
    i, j, steps, mind = merge_pairs([(r["keys"], r["steps"], r["min_km"]) for r in res], n)
    # docked/attached objects (e.g. ISS visiting vehicles) share an orbit permanently: not conjunctions
    keep = np.array([not co_orbiting(records[int(a)], records[int(b)]) for a, b in zip(i, j)], dtype=bool)
    n_co = int((~keep).sum())
    i, j, steps, mind = i[keep], j[keep], steps[keep], mind[keep]
    return {"i": i, "j": j, "steps": steps, "min_km": mind, "n_steps": n_steps,
            "timings": {"sweep_wall_s": wall, "merge_s": time.perf_counter() - t,
                        "propagate_cpu_s": sum(r["propagate_s"] for r in res),
                        "pairs_cpu_s": sum(r["pairs_s"] for r in res), "co_orbiting_dropped": n_co, "workers": workers, "chunks": len(tasks)}}


def score_graph(records: list[CatalogRecord], i: np.ndarray, j: np.ndarray) -> dict:
    """Degree, weighted degree, components and the super-spreader score (arrays of length N)."""
    n = len(records)
    deg = np.bincount(i, minlength=n) + np.bincount(j, minlength=n)
    adj = coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n))
    n_comp, labels = connected_components(adj, directed=False)
    mass = np.array([object_mass_kg(r) for r in records])
    crit = np.array([r.crit for r in records])
    # Degree centrality = degree / (N - 1). Raw mass is kept on purpose: a 420 t station fragmenting is a
    # bigger cascade seed than a 10 kg fragment. Shell-density criticality is the screener's proxy.
    raw = (deg / max(n - 1, 1)) * mass * crit
    score = raw / raw.max() if raw.size and raw.max() > 0 else raw
    return {"degree": deg, "n_components": int(n_comp), "labels": labels, "mass": mass, "crit": crit,
            "score": score}


def build_network(records: list[CatalogRecord], sw: dict, top: int = 300) -> dict:
    """JSON-serialisable summary: the top ``top`` nodes by score and the edges among them."""
    i, j, steps = sw["i"], sw["j"], sw["steps"]
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
    edges = [{"a": records[int(a)].norad, "b": records[int(b)].norad, "steps": int(s), "min_km": float(d)}
             for a, b, s, d in zip(i, j, steps, sw["min_km"]) if int(a) in keep_set and int(b) in keep_set]
    return {"nodes": nodes, "edges": edges,
            "summary": {"n_objects": n, "n_edges": int(len(i)), "n_components": sc["n_components"],
                        "largest_component": int(comp_sizes.max()) if len(comp_sizes) else 0,
                        "n_isolated": int((sc["degree"] == 0).sum()), "n_steps": sw["n_steps"]}}
