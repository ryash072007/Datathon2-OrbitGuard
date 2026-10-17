import numpy as np
import pandas as pd
import pytest

from orbitguard.decision import decision as D
from orbitguard.decision.features import build_table


def _tab(rows):
    """rows: list of (naive_risk, obj_type, span_days, miss_distance)."""
    return pd.DataFrame({
        "naive_risk": [r[0] for r in rows], "c_object_type": [r[1] for r in rows],
        "time_span_days": [r[2] for r in rows], "miss_distance": [r[3] for r in rows]})


def test_promotion_bands():
    p = {**D.DEFAULT_RULES, "w1": -6.04, "v1": -5.95, "w2": -7.3, "v2": -5.0}
    t = _tab([(-6.02, "DEBRIS", 2, 1e3), (-7.0, "DEBRIS", 2, 1e3), (-8.0, "DEBRIS", 2, 1e3),
              (-4.0, "DEBRIS", 2, 1e3)])
    assert list(D.apply_rules(t, p)) == [-5.95, -5.0, -8.0, -4.0]


def test_force_low_and_cap():
    p = {**D.DEFAULT_RULES, "miss_m": 30000.0, "payload": True, "span_days": 0.5,
         "cap_lo": -4.0, "cap_hi": -3.5}
    t = _tab([(-3.0, "DEBRIS", 2, 4.1e4), (-3.0, "PAYLOAD", 2, 1e3), (-3.0, "DEBRIS", 0.2, 1e3),
              (-3.0, "DEBRIS", 2, 1e3), (-5.0, "DEBRIS", 2, 1e3)])
    out = D.apply_rules(t, p)
    assert list(out[:3]) == [D.LOW] * 3
    assert out[3] == -3.5 and out[4] == -4.0


def _synthetic(n=400, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for e in range(n):
        hi = e % 10 == 0
        k = rng.integers(2, 6)
        ttca = np.sort(rng.uniform(2.1, 6, k))[::-1]
        risk = (-5.5 if hi else -8.0) + rng.normal(0, 0.3, k)
        for t, r in zip(ttca, risk):
            rows.append({"event_id": e, "time_to_tca": t, "risk": r, "mission_id": 3,
                         "c_object_type": "DEBRIS" if e % 3 else "PAYLOAD",
                         "miss_distance": 500.0 + 100 * rng.random(), "max_risk_estimate": r + 0.5,
                         "mahalanobis_distance": 10.0})
    df = pd.DataFrame(rows)
    labels = pd.Series({e: (-5.5 if e % 10 == 0 else -8.0) for e in range(n)})
    return df, labels


def test_synthetic_end_to_end_and_decision_fields():
    df, labels = _synthetic()
    tab = build_table(df, labels)
    folds = D._folds(tab)
    rules = D.fit_rules(tab, folds)
    clf = D.fit_classifier(tab)
    art = {"chosen": "C", "rules": rules, "gate": {"t_hi": 0.6, "t_lo": 0.0, "v_hi": -5.0},
           "classifier": clf, "interval": D.fit_interval(tab), "t_act": 0.5, "t_wait": 0.25}
    d = D.decide(df[df["event_id"] == 0], art)
    assert isinstance(d, D.Decision)
    assert isinstance(d.latest_risk, float) and isinstance(d.predicted_risk, float)
    assert 0.0 <= d.p_high <= 1.0 and len(d.interval) == 2 and d.interval[0] <= d.interval[1]
    assert d.action in ("ACT", "WAIT", "MONITOR") and d.reasons and all(isinstance(r, str) for r in d.reasons)
    assert D.decide(df[df["event_id"] == 0], art).action == "ACT"
    assert D.decide(df[df["event_id"] == 1], art).action == "MONITOR"


@pytest.mark.skipif(not (D.DECISION_PATH.exists() and (D.DATA / "test_data.csv").exists()),
                    reason="models/decision.joblib or data absent")
def test_saved_model_predict_risk():
    from orbitguard.decision.predict import predict_risk
    df = pd.read_csv(D.DATA / "test_data.csv", nrows=3000)
    ev = df[df["event_id"] == df[df["time_to_tca"] >= 2]["event_id"].iloc[0]]
    d = D.decide(ev)
    assert predict_risk(ev) == d.predicted_risk and d.action in ("ACT", "WAIT", "MONITOR")


def test_forecast_service_reports_decision_layer(tmp_path):
    """The validated forecast service carries Act/Wait/Monitor beside its forecast once decision.joblib exists."""
    import joblib

    from orbitguard.ml.service import MLService
    df, labels = _synthetic()
    tab = build_table(df, labels)
    art = {"chosen": "C", "rules": D.fit_rules(tab, D._folds(tab)), "gate": {"t_hi": 0.6, "t_lo": 0.0, "v_hi": -5.0},
           "classifier": D.fit_classifier(tab), "interval": D.fit_interval(tab), "t_act": 0.5, "t_wait": 0.25}
    svc = MLService(tmp_path)
    rows = df[df["event_id"] == 0]
    assert svc._decision_layer(rows)["status"] == "missing"
    (tmp_path / "artifacts" / "ml").mkdir(parents=True)
    joblib.dump(art, tmp_path / "artifacts" / "ml" / "decision.joblib")
    out = svc._decision_layer(rows)
    assert out["status"] == "ready" and out["action"] in {"ACT", "WAIT", "MONITOR"}
    assert out["interval_log10_pc"][0] <= out["predicted_log10_pc"] <= out["interval_log10_pc"][1]
    assert svc._decision_layer(rows[["event_id", "time_to_tca", "risk"]])["status"] == "unavailable"


def test_paired_bootstrap_shape_and_undefined_counted():
    # 3 events, one high-risk: resamples without it have undefined L and must be counted, not dropped
    true = np.array([-4.0, -4.5, -8.0, -9.0, -8.5, -9.5])
    naive = np.array([-4.0, -8.0, -8.0, -9.0, -8.5, -9.5])
    pred = np.array([-4.0, -4.5, -8.0, -9.0, -5.0, -9.5])
    out = D.paired_bootstrap(true, naive, pred, repeats=200, seed=1)
    e = out["metrics"]["L"]
    assert out["repeats"] == 200 and set(out["metrics"]) == {"L", "mse_hr", "f2", "precision"}
    assert e["n_undefined"] > 0
    assert e["ci95_lo"] <= e["ci95_hi"] and 0.0 <= e["frac_A_better"] <= 1.0
    assert out["metrics"]["f2"]["n_undefined"] == 0
