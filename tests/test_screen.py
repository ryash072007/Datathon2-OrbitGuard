"""Fast offline smoke tests for the manoeuvre screener (no network)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from src.screen.burns import Burn, burn_grid
from src.screen.catalog import compute_criticality, parse_tle_text
from src.screen.propagate import (J2, as_utc, delta_on_grid, integrate_j2, make_satrec, maneuvered_positions,
                                  rtn_basis, rtn_to_inertial, semi_major_axis_km, sgp4_track)
from src.screen.screen import prepare, run_burns

L1 = "1 25544U 98067A   26289.78971908  .00007803  00000+0  15012-3 0  9995"
L2 = "2 25544  51.6326  58.3278 0006748 271.9059  88.1156 15.48899044590607"


def _epoch(sat):
    from sgp4.api import jday  # noqa: F401
    from datetime import datetime, timezone
    # epoch from the TLE: year 2026, day-of-year 289.78971908
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=289.78971908 - 1)


def _variant(norad: int, d_ma_deg: float = 0.0, n_rev_day: float | None = None, inc: float | None = None) -> tuple[str, str]:
    l1 = L1[:2] + f"{norad:05d}" + L1[7:]
    ma = float(L2[43:51]) + d_ma_deg
    l2 = L2[:2] + f"{norad:05d}" + L2[7:43] + f"{ma:8.4f}" + L2[51:]
    if inc is not None:
        l2 = l2[:8] + f"{inc:8.4f}" + l2[16:]
    if n_rev_day is not None:
        l2 = l2[:52] + f"{n_rev_day:11.8f}" + l2[63:]
    return l1, l2


def test_rtn_orthonormal():
    sat = make_satrec(L1, L2)
    r, v = sgp4_track(sat, _epoch(sat), np.array([0.0]))
    b = rtn_basis(r[0], v[0])
    assert np.allclose(b @ b.T, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(b), 1.0)
    assert np.allclose(b[0], r[0] / np.linalg.norm(r[0]))
    assert np.allclose(b[2], np.cross(r[0], v[0]) / np.linalg.norm(np.cross(r[0], v[0])))
    assert b[1] @ v[0] > 0  # along-track is roughly along the velocity


def test_j2_matches_sgp4_over_one_orbit():
    sat = make_satrec(L1, L2)
    t0 = _epoch(sat)
    offs = np.arange(0, 5580.0, 60.0)
    r, v = sgp4_track(sat, t0, offs)
    traj = integrate_j2(np.concatenate([r[0], v[0]])[None], 552, 10.0, 6)[0]
    err = np.linalg.norm(traj[:, :3] - r, axis=1)
    assert err.max() < 15.0, err.max()  # J2-only vs full SGP4 (drag, J3/J4, mean/osculating): few km
    assert J2 > 0


def test_plus_t_burn_raises_sma_and_period():
    sat = make_satrec(L1, L2)
    r, v = sgp4_track(sat, _epoch(sat), np.array([0.0]))
    a0 = semi_major_axis_km(r[0], v[0])
    dv = rtn_to_inertial(np.array([0.0, 0.01, 0.0]), r[0], v[0])  # +T 10 m/s
    a1 = semi_major_axis_km(r[0], v[0] + dv)
    assert a1 > a0
    period = lambda a: 2 * np.pi * np.sqrt(a ** 3 / 398600.4418)  # noqa: E731
    assert period(a1) > period(a0)


def test_zero_dv_equals_sgp4_baseline():
    sat = make_satrec(L1, L2)
    man, base = maneuvered_positions(sat, _epoch(sat), 120, 10, (0.0, 0.0, 0.0))
    assert np.array_equal(man, base)
    d = delta_on_grid(*[x[10] for x in sgp4_track(sat, _epoch(sat), np.arange(120) * 60.0)],
                      np.array([[0.0, 1e-5, 0.0]]), 10, 120)
    assert np.all(d[0, :10] == 0) and np.linalg.norm(d[0, -1, :3]) > 0


def test_catalog_parse_and_criticality():
    recs = parse_tle_text(f"ISS\n{L1}\n{L2}\n{_variant(90001)[0]}\n{_variant(90001)[1]}\n")
    assert [r.norad for r in recs] == [25544, 90001]
    assert 400 < recs[0].perigee_km < 430 and recs[0].apogee_km >= recs[0].perigee_km
    compute_criticality(recs)
    assert all(0.0 <= r.crit <= 1.0 for r in recs)


def test_screen_finds_synthetic_approach_and_baseline_has_no_new_conjunctions(tmp_path):
    sat = make_satrec(L1, L2)
    tca = (as_utc(_epoch(sat)) + timedelta(hours=1)).replace(microsecond=0)
    near = _variant(90001, d_ma_deg=0.1, inc=51.7326)  # ~11 km ahead, inclination +0.1 deg (not co-orbiting)
    far = _variant(90002, n_rev_day=15.0)  # much higher orbit, removed by the prefilter
    burns = [Burn("none", "none", 0.0, tca - timedelta(minutes=30)),
             Burn("+T_0.1_0.5P", "+T", 0.1, tca - timedelta(minutes=30), 0.5),
             Burn("+T_0.5_0.5P", "+T", 0.5, tca - timedelta(minutes=30), 0.5)]
    ctx = prepare((L1, L2), [near, far], tca, burns, target_km=2.0, r_km=20.0, cache_dir=tmp_path)
    assert ctx.threat_norad == 90001 and len(ctx.tles) == 1
    # brute force: dense 1 s SGP4 within +-300 s of TCA
    offs = (tca - ctx.t0).total_seconds() + np.arange(-300.0, 301.0)
    rp, _ = sgp4_track(sat, ctx.t0, offs)
    ro, _ = sgp4_track(make_satrec(*near), ctx.t0, offs)
    brute = np.linalg.norm(rp - ro, axis=1).min()
    assert abs(ctx.baseline_miss_km - brute) < 1e-6
    assert 5.0 < brute < 20.0 and ctx.threat_idx in ctx.base_close
    df = run_burns(ctx, burns, workers=1)
    base = df[df["direction"] == "none"].iloc[0]
    assert base["new_conjunctions"] == 0 and abs(base["miss_km_threat"] - brute) < 1e-6
    assert set(["burn_id", "direction", "dv_mps", "burn_time_utc", "miss_km_threat", "new_conjunctions",
                "crit_penalty", "score", "feasible"]) <= set(df.columns)
    assert df["feasible"].iloc[0]  # feasible burns are ranked first


def test_burn_grid_shape():
    tca = as_utc(_epoch(make_satrec(L1, L2)))
    g = burn_grid(tca, 92.0)
    assert len(g) == 6 * 6 * 4 + 1
    assert g[-1].direction == "none" and sum(b.analytic_seed for b in g) == 2 * 6 * 4
