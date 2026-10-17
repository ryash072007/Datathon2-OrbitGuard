"""Validated Pc on catalogue states, and the all-object vs pair-only policy on screened candidates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from orbitguard.catalog.collision import encounter_pc
from orbitguard.catalog.screen import recommend
from orbitguard.consequence.pc import pc_isotropic


def _crossing(miss_km: float):
    """Primary on a circular LEO orbit; the other object crosses at ~6.7 km/s, offset radially by miss_km."""
    r1, v1 = np.array([7000.0, 0.0, 0.0]), np.array([0.0, 7.5, 0.0])
    r2, v2 = r1 + np.array([miss_km, 0.0, 0.0]), np.array([0.0, 3.0, 6.0])
    return r1, v1, r2, v2


def test_encounter_pc_matches_isotropic_and_reports_plane_miss():
    r1, v1, r2, v2 = _crossing(1.0)
    iso = 1000.0 / np.sqrt(2.0)  # per-object isotropic sigma (m) -> combined 1 km
    out = encounter_pc(r1, v1, r2, v2, sigma_rtn_m=(iso, iso, iso), hbr_m=20.0)
    # rtn_covariance is isotropic here, so the encounter-plane covariance is 1 km^2 in every direction
    assert abs(out["pc"] / pc_isotropic(out["miss_km"], 1.0, 20.0) - 1.0) < 1e-6
    assert out["pc_worst"] >= out["pc"] and set(out["by_scale"]) == {"0.5", "1.0", "2.0"}
    assert 0.0 < out["miss_km"] <= 1.0 + 1e-9


def test_pc_falls_with_miss_distance():
    near = encounter_pc(*_crossing(0.2))["pc"]
    far = encounter_pc(*_crossing(5.0))["pc"]
    assert near > far > 0.0


def _candidates():
    rows = [  # burn, dv, miss, threat worst Pc, worst other Pc
        ("none", 0.0, 0.3, 3e-3, 0.0),
        ("+T_0.1", 0.1, 4.0, 1e-7, 5e-3),   # cheapest pair-wise fix, but steers into another object
        ("+T_0.2", 0.2, 6.0, 1e-8, 1e-9),   # the safe choice
        ("-R_0.5", 0.5, 9.0, 1e-9, 0.0),
    ]
    df = pd.DataFrame(rows, columns=["burn_id", "dv_mps", "miss_km_threat", "threat_pc_worst", "worst_other_pc"])
    df["direction"] = ["none", "+T", "+T", "-R"]
    df["burn_time_utc"] = "2026-10-18T00:00:00+00:00"
    df["lead_periods"] = [0.0, 1.0, 1.0, 1.0]
    df["threat_pc"] = df["threat_pc_worst"] / 2
    df["worst_other_norad"] = [None, 12345, 22222, None]
    df["worst_pc"] = df[["threat_pc_worst", "worst_other_pc"]].max(axis=1)
    df["new_conjunctions"] = [0, 1, 0, 0]
    df["pc_valid"] = True
    df["feasible"] = df["miss_km_threat"] >= 2.0
    df["accepted"] = df["feasible"] & (df["worst_pc"] <= 1e-4)
    return df


def test_pair_only_introduces_hazard_orbitguard_does_not():
    pol = recommend(_candidates(), 1e-4)
    assert pol["status"] == "recommended"
    assert pol["pair_only"]["burn_id"] == "+T_0.1" and pol["pair_only"]["introduced_secondary_hazard"]
    assert pol["orbitguard"]["burn_id"] == "+T_0.2" and pol["orbitguard"]["worst_pc"] <= 1e-4


def test_policy_brief_is_grounded(facts):
    from orbitguard.brief.backends import llm_view
    from orbitguard.brief.grounding import check_grounding
    from orbitguard.brief.template import render_template
    pol = recommend(_candidates(), 1e-4)
    facts = {**facts, "risk": {**facts["risk"], "live_pc_worst": 3.1e-9},
             "burns": {**facts["burns"], "policies": pol}}
    text = render_template(facts)
    assert "+T_0.2" in text and "pair-only" in text and check_grounding(text, facts) == []
    view = llm_view(facts)
    assert view["recommendation"]["burn"] == "+T_0.2" and view["pair_only_comparison"]["burn"] == "+T_0.1"


def test_abstains_when_nothing_is_acceptable():
    df = _candidates()
    df["accepted"] = False
    pol = recommend(df, 1e-4)
    assert pol["status"] == "abstained" and pol["orbitguard"] is None
