"""Super-spreader network on a synthetic catalogue (no SGP4, no network)."""
from __future__ import annotations

import numpy as np

from src.network.graph import build_network, merge_pairs, pairs_from_positions, score_graph
from src.screen.catalog import CatalogRecord

L2 = "2 {n:05d}  51.6326  58.3278 0006748 271.9059  88.1156 15.48899044590607"


def _rec(norad: int, name: str, crit: float = 0.5) -> CatalogRecord:
    return CatalogRecord(name, norad, "1 x", L2.format(n=norad), "active", 500.0, 510.0, crit)


def _positions() -> np.ndarray:
    # 5 objects, 3 time steps. Object 0 is within 10 km of 1 and 2 (twice with 1); 3 and 4 are far from all.
    pos = np.zeros((5, 3, 3))
    pos[:, :, 0] = np.array([0.0, 5.0, 8.0, 500.0, 1000.0])[:, None]
    pos[1, 2, 0] = 400.0          # object 1 leaves at step 2
    pos[2, 1, 0] = 900.0          # object 2 leaves at step 1 and step 2? (only step 1 here)
    pos[4, 1, :] = np.nan         # SGP4 failure must be skipped
    return pos


def test_pairs_counts_and_min_distance():
    i, j, steps, mind = pairs_from_positions(_positions(), 10.0)
    got = {(int(a), int(b)): (int(s), float(d)) for a, b, s, d in zip(i, j, steps, mind)}
    assert got[(0, 1)] == (2, 5.0)      # steps 0 and 1
    assert got[(0, 2)] == (2, 8.0)      # steps 0 and 2
    assert got[(1, 2)][0] == 1 and abs(got[(1, 2)][1] - 3.0) < 1e-9
    assert (3, 4) not in got


def test_merge_pairs_adds_counts_and_takes_min():
    a = (np.array([1, 7]), np.array([2, 1]), np.array([3.0, 5.0]))
    b = (np.array([1]), np.array([4]), np.array([2.0]))
    i, j, s, d = merge_pairs([a, b], 4)
    assert list(zip(i, j, s, d)) == [(0, 1, 6, 2.0), (1, 3, 1, 5.0)]


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
