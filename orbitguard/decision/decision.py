"""Decision layer on top of the naive latest-CDM risk: learned rules (A), calibrated gate (B), both (C).

CLI: python -m orbitguard.decision.decision fit | eval
Parameters are learned by 5-fold GroupKFold CV on train only; the test set is used once in `eval`.
"""
from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from orbitguard.decision.evaluate import metrics
from orbitguard.decision.features import MIN_TTCA_DAYS, build_table
from orbitguard.decision.train import DATA, HIGH_RISK, RANDOM_STATE, ROOT, feature_matrix, usable_labels

DECISION_PATH = ROOT / "models" / "decision.joblib"
LOW = -6.001
FLOOR = -20.0
OBJ_TYPES = ["DEBRIS", "PAYLOAD", "ROCKET BODY", "TBA", "UNKNOWN"]
NUM_FEATS = ["naive_risk", "risk_slope", "risk_max", "max_risk_estimate", "log_miss_distance",
             "mahalanobis_distance", "time_to_tca", "n_cdms", "time_span_days"]

DEFAULT_RULES = {"w1": -6.0, "v1": -5.95, "w2": -6.0, "v2": -5.6, "miss_m": float("inf"),
                 "payload": False, "span_days": 0.0, "cap_lo": float("-inf"), "cap_hi": float("inf")}


# ----------------------------------------------------------------------------- rules (candidate A)
def _rule_masks(r, payload, span, miss, p: dict) -> dict:
    """Boolean masks for each rule. Bands: [w1,-6) -> v1 and [w2,w1) -> v2 (empty if w == upper edge)."""
    return {
        "band1": (r >= p["w1"]) & (r < HIGH_RISK),
        "band2": (r >= p["w2"]) & (r < p["w1"]),
        "payload": payload & bool(p["payload"]),
        "span": span < p["span_days"],
        "miss": miss > p["miss_m"],
        "cap": r >= HIGH_RISK,
    }


def force_low_mask(tab: pd.DataFrame, p: dict) -> np.ndarray:
    m = _rule_masks(tab["naive_risk"].to_numpy(), (tab["c_object_type"] == "PAYLOAD").to_numpy(),
                    tab["time_span_days"].to_numpy(), tab["miss_distance"].to_numpy(), p)
    return m["payload"] | m["span"] | m["miss"]


def apply_rules(tab: pd.DataFrame, p: dict) -> np.ndarray:
    r = tab["naive_risk"].to_numpy(dtype=float)
    m = _rule_masks(r, (tab["c_object_type"] == "PAYLOAD").to_numpy(), tab["time_span_days"].to_numpy(),
                    tab["miss_distance"].to_numpy(), p)
    pred = r.copy()
    pred[m["band1"]] = p["v1"]
    pred[m["band2"]] = p["v2"]
    pred[m["cap"]] = np.clip(r[m["cap"]], p["cap_lo"], p["cap_hi"])
    low = m["payload"] | m["span"] | m["miss"]
    pred[low] = np.minimum(pred[low], LOW)
    return pred


def explain_rules(row: pd.Series, p: dict) -> list[str]:
    t = row.to_frame().T.assign(naive_risk=row["naive_risk"])
    r = np.array([float(row["naive_risk"])])
    m = _rule_masks(r, np.array([row["c_object_type"] == "PAYLOAD"]), np.array([float(row["time_span_days"])]),
                    np.array([float(row["miss_distance"])]), p)
    out = []
    if m["payload"][0]:
        out.append("secondary object is a payload -> forced low")
    if m["span"][0]:
        out.append(f"CDM span {row['time_span_days']:.2f} d < {p['span_days']:.2f} d threshold -> forced low")
    if m["miss"][0]:
        out.append(f"miss distance {row['miss_distance'] / 1000:.0f} km > {p['miss_m'] / 1000:.0f} km "
                   f"threshold -> forced low")
    if m["band1"][0]:
        out.append(f"borderline risk {r[0]:.2f} promoted to {p['v1']}")
    if m["band2"][0]:
        out.append(f"near-borderline risk {r[0]:.2f} promoted to {p['v2']}")
    if m["cap"][0] and (r[0] < p["cap_lo"] or r[0] > p["cap_hi"]):
        out.append(f"high risk {r[0]:.2f} clipped to [{p['cap_lo']}, {p['cap_hi']}]")
    del t
    return out


def _rule_grids():
    bands = [(-6.0, -5.95, -6.0, -5.6)]  # empty bands = no-op
    w1s, v1s = [-6.04, -6.2, -6.4, -6.6, -7.0], [-5.95, -5.6, -5.0]
    w2s, v2s = [-6.4, -6.6, -7.0, -7.3, -7.6, -8.0], [-5.6, -5.0, -4.5]
    for w1, v1 in itertools.product(w1s, v1s):
        bands.append((w1, v1, w1, -5.6))
        for w2, v2 in itertools.product(w2s, v2s):
            if w2 < w1:
                bands.append((w1, v1, w2, v2))
    force = [(m, pl, s) for m in (float("inf"), 5e3, 10e3, 15e3, 20e3, 30e3, 50e3)
             for pl in (False, True) for s in (0.0, 0.25, 0.5, 1.0)]
    caps = [(lo, hi) for lo in (float("-inf"), -5.0, -4.5, -4.0) for hi in (float("inf"), -3.5, -3.0, -2.0)]
    return bands, force, caps


# ----------------------------------------------------------------------------- CV helpers
def _folds(tab: pd.DataFrame, n_splits: int = 5):
    return list(GroupKFold(n_splits=n_splits).split(tab, groups=tab.index.to_numpy()))


def _mean_L(true: np.ndarray, pred: np.ndarray, folds) -> float:
    Ls = [metrics(true[te], pred[te])["L"] for _, te in folds]
    return float(np.nanmean(Ls))


def fit_rules(tab: pd.DataFrame, folds) -> dict:
    """Coordinate-wise grid search (bands, then force-low, then cap; 2 rounds) minimising mean CV L."""
    true = tab["target"].to_numpy()
    bands, force, caps = _rule_grids()
    p = dict(DEFAULT_RULES)
    best = _mean_L(true, apply_rules(tab, p), folds)
    for _ in range(2):
        for group, keys in ((bands, ("w1", "v1", "w2", "v2")), (force, ("miss_m", "payload", "span_days")),
                            (caps, ("cap_lo", "cap_hi"))):
            for vals in group:
                q = {**p, **dict(zip(keys, vals))}
                L = _mean_L(true, apply_rules(tab, q), folds)
                if L < best - 1e-12:
                    best, p = L, q
    return p


# ----------------------------------------------------------------------------- classifier (candidate B)
def clf_matrix(tab: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=tab.index)
    X["naive_risk"] = tab["naive_risk"].clip(lower=FLOOR)
    X["risk_slope"] = tab["risk_slope"]
    X["risk_max"] = tab["risk_max"].clip(lower=FLOOR)
    X["max_risk_estimate"] = tab["max_risk_estimate"].clip(lower=FLOOR)
    X["log_miss_distance"] = np.log10(tab["miss_distance"].clip(lower=1.0))
    X["mahalanobis_distance"] = tab["mahalanobis_distance"] if "mahalanobis_distance" in tab else np.nan
    X["time_to_tca"] = tab["time_to_tca"]
    X["n_cdms"] = tab["n_cdms"]
    X["time_span_days"] = tab["time_span_days"]
    for o in OBJ_TYPES:
        X[f"obj_{o}"] = (tab["c_object_type"] == o).astype(float)
    return X


def make_classifier() -> CalibratedClassifierCV:
    base = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(class_weight="balanced", max_iter=2000))
    return CalibratedClassifierCV(base, method="isotonic", cv=5)


def fit_classifier(tab: pd.DataFrame) -> CalibratedClassifierCV:
    clf = make_classifier()
    clf.fit(clf_matrix(tab), (tab["target"].to_numpy() >= HIGH_RISK).astype(int))
    return clf


def proba(clf, tab: pd.DataFrame) -> np.ndarray:
    return clf.predict_proba(clf_matrix(tab))[:, 1]


def oof_proba(tab: pd.DataFrame, folds) -> np.ndarray:
    p = np.zeros(len(tab))
    for tr, te in folds:
        p[te] = proba(fit_classifier(tab.iloc[tr]), tab.iloc[te])
    return p


def apply_gate(naive: np.ndarray, p: np.ndarray, g: dict, force_low: np.ndarray | None = None) -> np.ndarray:
    pred = naive.copy()
    hi = p >= g["t_hi"]
    lo = (p < g["t_lo"]) & ~hi
    pred[hi] = np.maximum(naive[hi], g["v_hi"])
    pred[lo] = np.minimum(naive[lo], LOW)
    if force_low is not None:
        pred[force_low] = np.minimum(naive[force_low], LOW)
        # forced-low events cannot be lifted by the gate
    return pred


def fit_gate(naive, p, true, folds, force_low=None) -> dict:
    best, bg = np.inf, {"t_hi": 1.01, "t_lo": 0.0, "v_hi": -5.0}
    for t_hi, t_lo, v_hi in itertools.product([1.01] + [round(float(x), 2) for x in np.arange(0.2, 0.96, 0.05)],
                                              (0.0, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1),
                                              (-5.9, -5.5, -5.0, -4.5, -4.0)):
        g = {"t_hi": t_hi, "t_lo": t_lo, "v_hi": v_hi}
        L = _mean_L(true, apply_gate(naive, p, g, force_low), folds)
        if L < best - 1e-12:
            best, bg = L, g
    return bg


def pick_t_act(p: np.ndarray, true: np.ndarray) -> float:
    """Threshold on out-of-fold p_high maximising F2 (pooled)."""
    hr = true >= HIGH_RISK
    best, bt = -1.0, 0.5
    for t in np.arange(0.02, 0.99, 0.01):
        pr = p >= t
        tp = (hr & pr).sum()
        prec, rec = (tp / pr.sum() if pr.sum() else 0.0), tp / hr.sum()
        f2 = 5 * prec * rec / (4 * prec + rec) if 4 * prec + rec > 0 else 0.0
        if f2 > best + 1e-12:
            best, bt = f2, float(t)
    return round(bt, 2)


# ----------------------------------------------------------------------------- interval
def fit_interval(tab: pd.DataFrame) -> dict:
    X, levels = feature_matrix(tab, floor=FLOOR)
    resid = np.clip(tab["target"].to_numpy(), FLOOR, None) - np.clip(tab["naive_risk"].to_numpy(), FLOOR, None)
    models = {}
    for name, q in (("lo", 0.1), ("hi", 0.9)):
        m = HistGradientBoostingRegressor(
            loss="quantile", quantile=q, categorical_features="from_dtype", max_iter=200, learning_rate=0.05,
            max_depth=3, min_samples_leaf=20, random_state=RANDOM_STATE)
        m.fit(X, resid)
        models[name] = m
    return {"lo": models["lo"], "hi": models["hi"], "columns": list(X.columns), "levels": levels}


def interval_table(iv: dict, tab: pd.DataFrame, pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = tab.copy()
    for c in ("c_object_type",):
        t[c] = t[c].astype(str)
    X, _ = feature_matrix(t, levels=iv["levels"], floor=FLOOR)
    X = X[iv["columns"]]
    base = np.clip(tab["naive_risk"].to_numpy(), FLOOR, None)
    a, b = base + iv["lo"].predict(X), base + iv["hi"].predict(X)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    return np.minimum(lo, pred), np.maximum(hi, pred)  # always contains the point prediction


# ----------------------------------------------------------------------------- full predictor
def predict_all(art: dict, tab: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (predicted_risk, p_high) for a feature table."""
    naive = tab["naive_risk"].to_numpy(dtype=float)
    p = proba(art["classifier"], tab)
    ch = art["chosen"]
    if ch == "naive":
        pred = naive.copy()
    elif ch == "A":
        pred = apply_rules(tab, art["rules"])
    elif ch == "B":
        pred = apply_gate(naive, p, art["gate"])
    else:
        pred = apply_gate(naive, p, art["gate"], force_low_mask(tab, art["rules"]))
    return pred, p


@dataclass
class Decision:
    latest_risk: float
    predicted_risk: float
    p_high: float
    interval: tuple[float, float]
    action: str
    reasons: list[str]


_ART: dict | None = None


def load_artifact(path: Path = DECISION_PATH) -> dict:
    global _ART
    if _ART is None:
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: run `python -m orbitguard.decision.decision fit`")
        _ART = joblib.load(path)
    return _ART


def _driver(clf, X: pd.DataFrame) -> str:
    """Feature with the largest |coef * z| averaged over the calibrated base estimators."""
    contrib = np.zeros(X.shape[1])
    for cc in clf.calibrated_classifiers_:
        pipe = cc.estimator
        z = pipe[:-1].transform(X)[0]
        contrib += pipe[-1].coef_[0] * z
    i = int(np.argmax(np.abs(contrib)))
    return f"main driver: {X.columns[i]} ({'raises' if contrib[i] > 0 else 'lowers'} P(high))"


def decide(cdms: pd.DataFrame, art: dict | None = None) -> Decision:
    """CDM rows of ONE event -> Decision (uses CDMs with time_to_tca >= 2)."""
    art = art or load_artifact()
    u = cdms[cdms["time_to_tca"] >= MIN_TTCA_DAYS]
    if u.empty:
        raise ValueError("Event has no CDMs with time_to_tca >= 2 days")
    tab = build_table(u.assign(event_id=0))
    pred, p = predict_all(art, tab)
    pred_r, p_high = float(pred[0]), float(p[0])
    latest = float(tab["naive_risk"].iloc[0])
    lo, hi = interval_table(art["interval"], tab, pred)
    row = tab.iloc[0]
    if pred_r >= HIGH_RISK or p_high >= art["t_act"]:
        action = "ACT"
    elif p_high >= art["t_wait"]:
        action = "WAIT"
    else:
        action = "MONITOR"
    reasons = [f"latest CDM risk {latest:.2f} (log10 Pc), {int(row['n_cdms'])} CDMs over "
               f"{row['time_span_days']:.1f} d, last {row['time_to_tca']:.1f} d before TCA"]
    if art["chosen"] in ("A", "C"):
        reasons += explain_rules(row, art["rules"])
    if art["chosen"] in ("B", "C"):
        g = art["gate"]
        if p_high >= g["t_hi"]:
            reasons.append(f"classifier P(high)={p_high:.2f} >= {g['t_hi']} -> lifted to >= {g['v_hi']}")
        elif p_high < g["t_lo"]:
            reasons.append(f"classifier P(high)={p_high:.3f} < {g['t_lo']} -> capped below -6")
    reasons.append(f"P(final risk >= -6) = {p_high:.3f}; ACT if >= {art['t_act']}, WAIT if >= {art['t_wait']}")
    reasons.append(_driver(art["classifier"], clf_matrix(tab)))
    if action == "WAIT":
        reasons.append("borderline: wait for the next CDM before committing to a manoeuvre")
    return Decision(latest, pred_r, p_high, (float(lo[0]), float(hi[0])), action, reasons)


# ----------------------------------------------------------------------------- CLI
def _train_table() -> pd.DataFrame:
    train = pd.read_csv(DATA / "train_data.csv")
    labels = usable_labels(train)
    return build_table(train[train["event_id"].isin(labels.index)], labels)


def cmd_fit(out: Path) -> None:
    tab = _train_table()
    true = tab["target"].to_numpy()
    naive = tab["naive_risk"].to_numpy(dtype=float)
    folds = _folds(tab)
    print(f"train events {len(tab)}, high-risk final {int((true >= HIGH_RISK).sum())}")

    rules = fit_rules(tab, folds)
    p_oof = oof_proba(tab, folds)
    gate_b = fit_gate(naive, p_oof, true, folds)
    flow = force_low_mask(tab, rules)
    gate_c = fit_gate(naive, p_oof, true, folds, flow)

    preds = {"naive": naive, "A": apply_rules(tab, rules), "B": apply_gate(naive, p_oof, gate_b),
             "C": apply_gate(naive, p_oof, gate_c, flow)}
    table, cvL = [], {}
    for k, v in preds.items():
        cvL[k] = _mean_L(true, v, folds)
        pm = metrics(true, v)
        table.append((k, cvL[k], pm["L"], pm["mse_hr"], pm["f2"]))
    print(f"{'cand':6}{'meanCV_L':>10}{'pooledL':>10}{'pooledMSE_HR':>14}{'pooledF2':>10}")
    for r in table:
        print(f"{r[0]:6}{r[1]:10.3f}{r[2]:10.3f}{r[3]:14.3f}{r[4]:10.3f}")
    chosen = min(cvL, key=lambda k: cvL[k])  # ties resolve to naive (first)
    if chosen == "naive":
        print("NOTE: nothing beats naive on CV; decision layer keeps predicted_risk = naive")
    t_act = pick_t_act(p_oof, true)
    t_wait = round(t_act / 2, 2)
    print(f"chosen: {chosen}\nrules: {rules}\ngate B: {gate_b}\ngate C: {gate_c}\n"
          f"t_act={t_act} (max OOF F2), t_wait={t_wait} (t_act/2)")
    art = {"chosen": chosen, "rules": rules, "gate": gate_c if chosen == "C" else gate_b,
           "classifier": fit_classifier(tab), "interval": fit_interval(tab),
           "t_act": t_act, "t_wait": t_wait, "cv": {k: float(v) for k, v in cvL.items()}}
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(art, out)
    print(f"saved {out}")


def cmd_eval(path: Path) -> None:
    art = joblib.load(path)
    test = pd.read_csv(DATA / "test_data.csv")
    priv = pd.read_csv(DATA / "test_data_private.csv").set_index("event_id")["true_risk"]
    tab = build_table(test, priv)
    true = tab["target"].to_numpy()
    pred, p = predict_all(art, tab)
    res = {"naive": metrics(true, tab["naive_risk"].to_numpy(dtype=float)), art["chosen"]: metrics(true, pred)}
    keys = ["L", "mse_hr", "f2", "precision", "recall"]
    print(f"test events {len(tab)}; chosen = {art['chosen']}")
    print(f"{'':8}" + "".join(f"{k:>11}" for k in keys))
    for n, m in res.items():
        print(f"{n:8}" + "".join(f"{m[k]:11.3f}" for k in keys))
    lo, hi = interval_table(art["interval"], tab, pred)
    t = np.clip(true, FLOOR, None)
    print(f"80% interval empirical coverage on test: {np.mean((t >= lo) & (t <= hi)):.3f} "
          f"(mean width {np.mean(hi - lo):.2f})")
    ids = tab.index[(true >= HIGH_RISK)]
    eid = ids[0] if len(ids) else tab.index[0]
    print("example event", eid, "true risk", round(float(priv.loc[eid]), 2))
    print(decide(test[test["event_id"] == eid], art))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "eval"])
    ap.add_argument("--path", type=Path, default=DECISION_PATH)
    a = ap.parse_args()
    cmd_fit(a.path) if a.cmd == "fit" else cmd_eval(a.path)


if __name__ == "__main__":
    main()
