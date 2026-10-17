"""Fast synthetic tests for the consequence engine (no network)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from orbitguard.consequence.breakup import (LC_MIN_M, POWER, generate_fragments, is_catastrophic, n_fragments,
                                     sample_lengths)
from orbitguard.consequence.cloud import build_density, to_orbits
from orbitguard.consequence.exposure import compute_exposure
from orbitguard.consequence.pc import pc_isotropic
from orbitguard.catalog.catalog import parse_tle_text

L1 = "1 25544U 98067A   26289.78971908  .00007803  00000+0  15012-3 0  9995"
L2 = "2 25544  51.6326  58.3278 0006748 271.9059  88.1156 15.48899044590607"
R0 = np.array([6778.0, 0.0, 0.0])
V0 = np.array([0.0, 5.0, 5.7])  # ~51.6 deg-ish inclined, near circular at 400 km
V_CIRC = float(np.sqrt(398600.4418 / 6778.0))


def _frags(n_max=3000, seed=0, m1=500.0, m2=500.0):
    v1 = np.array([0.0, V_CIRC, 0.0])
    v2 = np.array([0.0, -V_CIRC * 0.5, 7.0])
    return generate_fragments(m1, m2, R0, v1, R0, v2, np.random.default_rng(seed), n_max)


def test_fragment_count_and_length_law():
    f = _frags()
    assert f.catastrophic
    assert abs(len(f.lc_m) - min(round(n_fragments(1000.0)), 3000)) <= 1
    big = generate_fragments(1e5, 1e5, R0, V0, R0, -V0, np.random.default_rng(1), 100000)
    assert len(big.lc_m) == round(big.n_true)
    # fraction above 0.3 m must follow the truncated power law (sampling error ~ 4 sigma)
    a, b = LC_MIN_M**-POWER, 1.0
    expect = (0.3**-POWER - b) / (a - b)
    got = np.mean(big.lc_m > 0.3)
    se = np.sqrt(expect * (1 - expect) / len(big.lc_m))
    assert abs(got - expect) < 4 * se
    assert big.lc_m.min() >= LC_MIN_M and big.lc_m.max() <= 1.0
    # weight bookkeeping when capped
    capped = _frags(n_max=100)
    assert len(capped.lc_m) == 100 and abs(capped.weight * 100 - capped.n_true) < 1e-9


def test_delta_v_log_mean():
    f = generate_fragments(1e6, 1e6, R0, V0, R0, -V0, np.random.default_rng(2), 20000)
    resid = np.log10(f.dv_mps) - (0.9 * f.chi + 2.9)
    assert abs(resid.mean()) < 4 * 0.4 / np.sqrt(len(resid))
    assert abs(resid.std() - 0.4) < 0.02
    assert abs(f.chi.mean() - (-0.6)) < 0.03
    # isotropic: mean ejection direction ~ 0 so the cloud keeps the centre-of-mass velocity
    vcm = (1e6 * V0 + 1e6 * -V0) / 2e6
    assert np.linalg.norm((f.vel_kms - vcm).mean(axis=0)) < 0.05 * np.median(f.dv_mps) / 1000.0 * 5


def test_catastrophic_threshold():
    # 0.5 * 1 kg * (8 km/s)^2 / 100 kg = 160 J/g -> catastrophic; with 1000 kg target: 16 J/g -> not
    assert is_catastrophic(1.0, 100.0, 8.0)
    assert not is_catastrophic(1.0, 1000.0, 8.0)
    # exactly around 40 J/g: 0.5*m*(v*1000)^2/(M*1000) = 40  ->  v = sqrt(80 M/m)/ sqrt(1000)... check both sides
    m, big = 10.0, 1000.0
    v_crit = np.sqrt(40.0 * big * 1000.0 * 2.0 / m) / 1000.0
    assert not is_catastrophic(m, big, v_crit * 0.99) and is_catastrophic(m, big, v_crit * 1.01)
    f = generate_fragments(1.0, 1000.0, R0, V0, R0, -V0 * 0.1, np.random.default_rng(0))
    assert not f.catastrophic
    v = np.linalg.norm(V0 * 1.1)
    assert abs(f.ejected_mass_kg - 1.0 * v**2) < 1e-6


def test_density_total_weight_is_consistent():
    f = _frags(n_max=400)
    orb = to_orbits(f.pos_km, f.vel_kms, 1.0)
    n_days, k = 30, 8
    grid = build_density(orb, n_days, k, seed=0)
    assert abs(grid.total_weight - len(orb.a) * k * n_days) < 1e-6
    assert grid.vsum.shape == (len(grid.keys), 3) and np.all(np.diff(grid.keys) > 0)
    # re-entering fragments are removed and counted
    assert orb.n_input == len(f.lc_m) and len(orb.a) + orb.n_reentered + orb.n_unbound == orb.n_input
    # with non-unit weights the histogram total scales with the weights
    grid2 = build_density(to_orbits(f.pos_km, f.vel_kms, 2.5), n_days, k, seed=0)
    assert abs(grid2.total_weight - 2.5 * grid.total_weight) < 1e-6


def test_cloud_stays_near_parent_altitude():
    v1, v2 = np.array([0.0, V_CIRC, 0.0]), np.array([0.0, 0.0, V_CIRC])
    f = generate_fragments(5e5, 5.0, R0, v1, R0, v2, np.random.default_rng(0), 500)  # small hits big: cm ~ v1
    assert not f.catastrophic
    orb = to_orbits(f.pos_km, f.vel_kms, 1.0)
    assert len(orb.a) > 100
    from orbitguard.consequence.cloud import positions_at
    pos, _, _ = positions_at(orb, 86400.0, 4, np.random.default_rng(0))
    alt = np.linalg.norm(pos, axis=1) - 6378.137
    assert 150 < np.median(alt) < 700 and np.all(alt > 0)


def test_no_fragments_zero_exposure():
    grid = build_density(to_orbits(np.zeros((0, 3)), np.zeros((0, 3)), 1.0), 5, 4)
    assert grid.total_weight == 0.0
    sats = parse_tle_text(f"ISS\n{L1}\n{L2}\n")
    e = compute_exposure(grid, sats, datetime(2026, 10, 18, tzinfo=timezone.utc), n_days=5, phases=4)
    assert e.shape == (1,) and e[0] == 0.0


def test_exposure_positive_for_sat_inside_cloud():
    # a cloud generated right at the satellite's own orbit must give it a non-zero exposure
    sats = parse_tle_text(f"ISS\n{L1}\n{L2}\n")
    from orbitguard.consequence.event import state_at
    tca = datetime(2026, 10, 18, 4, 0, tzinfo=timezone.utc)
    r, v = state_at(sats[0], tca)
    f = generate_fragments(500.0, 500.0, r + 5.0, v, r + 5.0, -0.3 * v, np.random.default_rng(0), 500)
    grid = build_density(to_orbits(f.pos_km, f.vel_kms, f.weight), 3, 8)
    e = compute_exposure(grid, sats, tca, n_days=3, phases=16)
    assert e[0] >= 0.0 and np.isfinite(e[0])


def test_pc_isotropic():
    sigma, hbr = 1.0, 20.0
    # exact disk integral: 1 - exp(-HBR^2 / (2 sigma^2)) at zero miss; the small-HBR form agrees to ~1e-4 relative
    exact = 1.0 - np.exp(-(0.02**2) / (2 * sigma**2))
    assert abs(pc_isotropic(0.0, sigma, hbr) - exact) < 1e-9 * exact
    assert abs(pc_isotropic(0.0, sigma, hbr) / ((0.02**2) / (2 * sigma**2)) - 1.0) < 1e-3
    vals = [pc_isotropic(d) for d in (0.0, 0.5, 1.0, 2.0, 5.0)]
    assert all(a > b for a, b in zip(vals, vals[1:]))
    assert pc_isotropic(0.0, 2.0, 20.0) < pc_isotropic(0.0, 1.0, 20.0)
