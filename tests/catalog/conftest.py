"""Shared synthetic fixtures for the Phase 5 tests (no network, no model)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def facts() -> dict:
    return {
        "generated_utc": "2026-10-17T10:00:00+00:00",
        "event": {"primary": {"name": "ISS (ZARYA)", "norad": 25544, "type": "PAYLOAD", "mass_kg": 420000.0},
                  "threat": {"name": "DEBRIS ONE", "norad": 64962, "type": "DEBRIS", "mass_kg": 10.0},
                  "tca_utc": "2026-10-18T04:48:38+00:00", "miss_km": 4.9812, "search_window_days": 3.0},
        "risk": {"live_pc": 8.31e-10, "pc_note": "isotropic",
                 "decision": {"label": "historical CDM example", "cdm_event_id": 8, "latest_risk_log10_pc": -6.37,
                              "predicted_risk_log10_pc": -6.3757, "p_high": 0.0612, "interval_log10_pc": [-7.5, -5.2],
                              "action": "WAIT", "reasons": ["reason one"]}},
        "burns": {"baseline_miss_km": 4.98, "target_km": 10.0, "n_screened": 144, "n_feasible": 4,
                  "n_objects_screened": 6762,
                  "top": [{"burn_id": "+T_0.5_3P", "direction": "+T", "dv_mps": 0.5, "lead_periods": 3.0,
                           "miss_km_threat": 22.31, "new_conjunctions": 0, "feasible": True, "along_track": True,
                           "score": 0.5},
                          {"burn_id": "+T_0.5_2P", "direction": "+T", "dv_mps": 0.5, "lead_periods": 2.0,
                           "miss_km_threat": 15.3, "new_conjunctions": 0, "feasible": True, "along_track": True,
                           "score": 0.5},
                          {"burn_id": "-T_0.5_3P", "direction": "-T", "dv_mps": 0.5, "lead_periods": 3.0,
                           "miss_km_threat": 22.0, "new_conjunctions": 1, "feasible": True, "along_track": True,
                           "score": 0.6}]},
        "consequence": {"catastrophic": False, "ejected_mass_kg": 28500.0, "fragments_true": 11259.4,
                        "reentered_fraction": 0.339, "pc": 8.31e-10, "n_sats_ge1_encounter": 8943,
                        "n_sats_any_exposure": 9500, "n_sats_considered": 15145,
                        "total_expected_encounters": 18337.2, "expected_harm": 1.52e-5,
                        "exposed_by_constellation": {"STARLINK": 5000, "ONEWEB": 400}, "v_rel_kms": 7.6,
                        "parent_alt_km": 420.0,
                        "top_satellites": [{"name": "SAT A", "expected_encounters": 3.2}],
                        "assumptions": {"min_fragment_cm": 10, "horizon_days": 30, "encounter_radius_km": 1.0,
                                        "sigma_km": 1.0, "hbr_m": 20.0, "mass_note": "approximate"}},
        "network": None,
        "timings_s": {"screen_s": 7.0},
    }


@pytest.fixture
def data_fixture(tmp_path, monkeypatch, facts):
    """DATA_DIR with cached facts, a tiny network file and a tiny survey CSV."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "facts_25544.json").write_text(json.dumps(facts), encoding="utf-8")
    nodes = [{"rank": i + 1, "norad": 1000 + i, "name": f"SAT-{i}", "type": "PAYLOAD", "group": "active",
              "degree": 5 - i, "wdegree": 10.0, "mass_kg": 800.0, "crit": 0.9, "score": 1.0 - 0.1 * i,
              "component_size": 4, "perigee_km": 500.0 + 10 * i, "apogee_km": 510.0 + 10 * i,
              "inclination_deg": 53.0 + i} for i in range(5)]
    net = {"generated_utc": "2026-10-17T10:00:00+00:00", "params": {"hours": 24, "step_s": 60, "r_km": 10, "top": 300},
           "timings": {"sweep_wall_s": 3.0, "workers": 12},
           "summary": {"n_objects": 100, "n_edges": 4, "n_components": 90, "largest_component": 5, "n_isolated": 80,
                       "n_steps": 1440},
           "nodes": nodes, "edges": [{"a": 1000, "b": 1001, "steps": 3, "min_km": 2.0}]}
    (out / "network_20261017T100000Z.json").write_text(json.dumps(net), encoding="utf-8")
    (out / "consequence_survey3_seed0_20261017T100000Z.csv").write_text(
        "primary,norad,threat,rank_pc,rank_harm\nISS (ZARYA),25544,X,1,3\nSTARLINK-1,44713,Y,2,1\n"
        "STARLINK-2,44714,Z,3,2\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    return tmp_path
