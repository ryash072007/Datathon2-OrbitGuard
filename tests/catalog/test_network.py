"""Super-spreader network on a synthetic catalogue (no SGP4, no network)."""
from __future__ import annotations

import numpy as np

from orbitguard.network.graph import build_network, encounters_from_state, merge_encounters, score_graph
from orbitguard.catalog.catalog import CatalogRecord

L2 = "2 {n:05d}  51.6326  58.3278 0006748 271.9059  88.1156 15.48899044590607"


def _rec(norad: int, name: str, crit: float = 0.5) -> CatalogRecord:
    return CatalogRecord(name, norad, "1 x", L2.format(n=norad), "active", 500.0, 510.0, crit)


def test_crossing_between_samples_is_detected():
    # Head-on pair, 10 km/s closing, 2 km miss in z, closest approach at t=7 s: between the t=0 and t=15 s
    # samples (70 km and 80 km apart). The old fixed-radius pair search at 10 km missed this.
    pos = np.zeros((2, 2, 3))
    vel = np.zeros((2, 2, 3))
    for t, dt in enumerate((0.0, 15.0)):
        pos[0, t] = [-35.0 + 5.0 * dt, 0.0, 0.0]
        pos[1, t] = [35.0 - 5.0 * dt, 0.0, 2.0]
    vel[0, :, 0], vel[1, :, 0] = 5.0, -5.0
    assert np.min(np.linalg.norm(pos[0] - pos[1], axis=1)) > 10.0
    k, st, d, v = encounters_from_state(pos, vel, 15.0, 10.0)
    i, j, enc, mind, maxv = merge_encounters([(k, st, d, v)], 2)
    assert (int(i[0]), int(j[0]), int(enc[0])) == (0, 1, 1)   # both steps hit, merged into one encounter
    assert abs(mind[0] - 2.0) < 1e-6 and abs(maxv[0] - 10.0) < 1e-9


def test_merge_encounters_splits_on_gaps_and_takes_extremes():
    key = np.array([1, 1, 1, 1, 7])
    step = np.array([3, 4, 9, 10, 5])
    dist = np.array([4.0, 2.0, 6.0, 5.0, 1.0])
    vrel = np.array([1.0, 3.0, 2.0, 2.0, 9.0])
    a, b = (key[:3], step[:3], dist[:3], vrel[:3]), (key[3:], step[3:], dist[3:], vrel[3:])
    i, j, enc, mind, maxv = merge_encounters([b, a], 4)
    assert list(zip(i, j, enc, mind, maxv)) == [(0, 1, 2, 2.0, 3.0), (1, 3, 1, 1.0, 9.0)]


def test_score_prefers_connected_heavy_and_critical():
    recs = [_rec(1, "STARLINK-1"), _rec(2, "STARLINK-2"), _rec(3, "STARLINK-3"), _rec(4, "ONEWEB-4"),
            _rec(5, "LONER")]
    i, j = np.array([0, 0, 3]), np.array([1, 2, 4])
    sc = score_graph(recs, i, j)
    assert list(sc["degree"]) == [2, 1, 1, 1, 1]
    assert sc["n_components"] == 2
    assert sc["score"].max() == 1.0 and int(np.argmax(sc["score"])) == 0
    assert 0.0 <= sc["score"].min()


def test_build_network_keeps_top_nodes_only():
    recs = [_rec(n, f"STARLINK-{n}") for n in range(1, 7)]
    sw = {"i": np.array([0, 0, 4]), "j": np.array([1, 2, 5]), "steps": np.array([3, 1, 2]),
          "min_km": np.array([1.0, 2.0, 3.0]), "n_steps": 10}
    net = build_network(recs, sw, top=3)
    assert len(net["nodes"]) == 3 and net["nodes"][0]["norad"] == 1
    assert net["summary"]["n_edges"] == 3 and net["summary"]["n_components"] == 3
    assert all(e["a"] in {n["norad"] for n in net["nodes"]} for e in net["edges"])
