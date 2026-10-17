"""Shape and determinism of the debris-cloud visualisation payload (synthetic TLEs, no network)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from orbitguard.catalog.catalog import parse_tle_text
from orbitguard.consequence.event import Params
from orbitguard.consequence.viz import EPOCHS_H, debris_payload

L1 = "1 25544U 98067A   26289.78971908  .00007803  00000+0  15012-3 0  9995"
L2 = "2 25544  51.6326  58.3278 0006748 271.9059  88.1156 15.48899044590607"


def _tle(norad: int, incl: float, raan: float, anom: float) -> str:
    l1 = L1.replace("25544", f"{norad:05d}", 1)
    l2 = f"2 {norad:05d} {incl:8.4f} {raan:8.4f} 0006748 271.9059 {anom:8.4f} 15.48899044590607"
    return f"SAT-{norad}\n{l1}\n{l2}\n"


def _records():
    text = f"ISS (ZARYA)\n{L1}\n{L2}\n" + _tle(90001, 60.0, 58.0, 88.0) + "".join(
        _tle(90100 + k, 51.0 + 0.3 * k, 58.0 + 2 * k, 88.0 + 7 * k) for k in range(12))
    return parse_tle_text(text, "active")


def _payload(seed: int = 0, max_sample: int = 200):
    rec = _records()
    tca = datetime(2026, 10, 18, 4, 0, tzinfo=timezone.utc)
    return debris_payload(rec[0], rec[1], tca, 3.0, rec, Params(seed=seed, max_fragments=400, n_days=5),
                          max_sample=max_sample, top_sats=5)


def test_payload_shape_and_json():
    p = _payload()
    n, k = p["n_sampled"], len(EPOCHS_H)
    assert 0 < n <= 200 and p["n_fragments_total"] >= p["n_fragments_modelled"] >= p["n_fragments_surviving"] >= n
    assert len(p["fragments"]["pos_km"]) == k and all(len(e) == 3 * n for e in p["fragments"]["pos_km"])
    el = p["fragments"]["elements"]
    assert len(el["a_km"]) == n and len(el["p"]) == 3 * n and len(el["m0_rad"]) == n
    # T+0: fragments start at the collision point
    cp = np.array(p["collision_point_km"])
    t0 = np.array(p["fragments"]["pos_km"][0]).reshape(-1, 3)
    assert np.linalg.norm(t0 - cp, axis=1).max() < 30.0
    # all fragments stay bound and above the surface
    r = np.linalg.norm(np.array(p["fragments"]["pos_km"][2]).reshape(-1, 3), axis=1)
    assert r.min() > 6378.0 and r.max() < 200000.0
    sats = p["satellites"]
    assert 0 < len(sats) <= 5 and all(len(s["pos_km"]) == k for s in sats)
    assert [s["exposure"] for s in sats] == sorted((s["exposure"] for s in sats), reverse=True)
    assert len(p["satellite_elements"]["a_km"]) == len(sats)
    assert p["collision_point_km"] and p["primary"]["name"] == "ISS (ZARYA)" and "no drag" in p["note"]
    json.dumps(p)


def test_payload_deterministic_and_seeded():
    a, b, c = _payload(0), _payload(0), _payload(1)
    assert json.dumps(a) == json.dumps(b)
    assert json.dumps(a["fragments"]) != json.dumps(c["fragments"])
