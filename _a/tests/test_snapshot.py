"""Globe snapshot payload: shapes, sizes, rounding (no network; two embedded TLEs)."""
from __future__ import annotations

import copy
import json

import numpy as np

from src.consequence.snapshot import cloud_snapshots
from src.screen.catalog import parse_tle_text

TLES = """ISS (ZARYA)
1 25544U 98067A   26289.78971908  .00007803  00000+0  15012-3 0  9995
2 25544  51.6326  58.3278 0006748 271.9059  88.1156 15.48899044590607
HST
1 20580U 90037B   26289.81451817  .00006765  00000+0  20539-3 0  9991
2 20580  28.4738 328.5189 0002049  75.0606 285.0217 15.31972242807235
"""


def _facts(facts: dict) -> dict:
    f = copy.deepcopy(facts)
    f["event"]["threat"].update(norad=20580, name="HST", mass_kg=11000.0)
    f["burns"]["top"][0]["burn_time_utc"] = "2026-10-18 00:09:43+00:00"
    return f


def test_snapshot_shapes_and_size(data_fixture, facts):
    recs = parse_tle_text(TLES, "active")
    g = cloud_snapshots(_facts(facts), n_points=300, records=recs)
    assert [s["day"] for s in g["snapshots"]] == [0.1, 1.0, 7.0, 30.0]
    for s in g["snapshots"]:
        pts = np.asarray(s["points"])
        assert pts.ndim == 2 and pts.shape[1] == 3 and len(pts) == s["n"] <= 300
        assert np.all(np.abs(pts * 10 - np.round(pts * 10)) < 1e-6)  # 1 decimal place
    assert len(g["tracks"]["primary"]) == 120 and len(g["tracks"]["threat"]) == 120
    assert g["burn"] and np.asarray(g["burn"]["points"]).shape[1] == 3 and g["burn"]["exaggeration"] > 1
    assert g["fragments_true"] == facts["consequence"]["fragments_true"]
    path = data_fixture / "out" / "globe_25544.json"
    assert path.exists() and json.loads(path.read_text(encoding="utf-8"))["norad"] == 25544
    assert path.stat().st_size < 400_000


def test_snapshot_without_burn_time(data_fixture, facts):
    f = _facts(facts)
    del f["burns"]["top"][0]["burn_time_utc"]
    g = cloud_snapshots(f, days=(1,), n_points=50, records=parse_tle_text(TLES, "active"), write=False)
    assert g["burn"] is None and len(g["snapshots"]) == 1
