"""Train the residual HistGradientBoosting risk model: python -m src.risk.train"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from src.risk.features import CAT_COLS, build_table

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "cac"
MODEL_PATH = ROOT / "models" / "risk_hgb.joblib"
HIGH_RISK = -6.0
HR_WEIGHT = 20.0
RANDOM_STATE = 42
FLOOR_COLS = ["risk", "risk_first", "risk_min", "risk_max", "risk_mean", "max_risk_estimate"]


def usable_labels(train: pd.DataFrame) -> pd.Series:
    """Final-CDM risk per event, for events with >=1 CDM at ttca>=2 and final ttca<1."""
    has_early = train.groupby("event_id")["time_to_tca"].max() >= 2
    final = train.sort_values(["event_id", "time_to_tca"]).groupby("event_id").first()
    ok = has_early & (final["time_to_tca"] < 1)
    return final.loc[ok[ok].index, "risk"]


def feature_matrix(tab: pd.DataFrame, levels: dict | None = None, floor: float | None = None):
    """Return (X, levels). Categorical columns become pandas category with fixed levels."""
    X = tab.drop(columns=[c for c in ["target", "naive_risk"] if c in tab.columns]).copy()
    if floor is not None:
        for c in FLOOR_COLS:
            if c in X.columns:
                X[c] = X[c].clip(lower=floor)
    X["mission_id"] = X["mission_id"].astype(int)
    if levels is None:
        levels = {c: sorted(X[c].unique().tolist()) for c in CAT_COLS}
    for c in CAT_COLS:
        X[c] = pd.Categorical(X[c], categories=levels[c])
    return X, levels


def sample_weights(naive: np.ndarray, final: np.ndarray) -> np.ndarray:
    return np.where((naive >= -8) | (final >= HIGH_RISK), HR_WEIGHT, 1.0)


def fit(tab: pd.DataFrame, floor: float | None = None, with_classifier: bool = False) -> dict:
    X, levels = feature_matrix(tab, floor=floor)
    naive = tab["naive_risk"].to_numpy()
    final = tab["target"].to_numpy()
    if floor is not None:
        naive_in, final_t = np.clip(naive, floor, None), np.clip(final, floor, None)
    else:
        naive_in, final_t = naive, final
    w = sample_weights(naive, final)
    reg = HistGradientBoostingRegressor(
        categorical_features="from_dtype", max_iter=300, learning_rate=0.05,
        max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1.0, random_state=RANDOM_STATE)
    reg.fit(X, final_t - naive_in, sample_weight=w)
    art = {"model": reg, "columns": list(X.columns), "levels": levels, "floor": floor,
           "classifier": None}
    if with_classifier:
        clf = HistGradientBoostingClassifier(
            categorical_features="from_dtype", max_iter=200, learning_rate=0.05,
            max_leaf_nodes=15, min_samples_leaf=10, class_weight="balanced",
            random_state=RANDOM_STATE)
        clf.fit(X, (final >= HIGH_RISK).astype(int))
        art["classifier"] = clf
    return art


CLIP_LO = -6.001
GATES = (-8.0, -7.0, -6.5)
SHIFT_GRID = [round(x, 1) for x in np.arange(-1.0, 0.51, 0.1)]


def predict_gated(art: dict, tab: pd.DataFrame) -> np.ndarray:
    naive = tab["naive_risk"].to_numpy()
    pred = naive.copy()
    gated = naive >= art["gate"]
    if art["kind"] == "shift":
        pred[gated] = np.clip(naive[gated] + art["shift"], -30.0, 0.0)
        return pred
    X, _ = feature_matrix(tab, levels=art["levels"], floor=CLIP_LO)
    X = X[art["columns"]]
    act = naive >= CLIP_LO
    if act.any():
        res = art["model"].predict(X[act])
        pred[act] = np.clip(np.clip(naive[act], CLIP_LO, None) + res, CLIP_LO, 0.0)
    return pred


def fit_gated(tab: pd.DataFrame, gate: float, loss: str) -> dict:
    sub = tab[tab["naive_risk"] >= gate]
    levels = {c: sorted(tab[c].unique().tolist()) for c in CAT_COLS}
    levels["c_object_type"] = sorted(set(levels["c_object_type"]) | {"UNKNOWN", "DEBRIS", "PAYLOAD", "ROCKET BODY", "TBA"})
    X, _ = feature_matrix(sub, levels=levels, floor=CLIP_LO)
    y = np.clip(sub["target"].to_numpy(), CLIP_LO, None) - np.clip(sub["naive_risk"].to_numpy(), CLIP_LO, None)
    reg = HistGradientBoostingRegressor(
        loss=loss, categorical_features="from_dtype", max_iter=200, learning_rate=0.05,
        max_depth=3, min_samples_leaf=20, l2_regularization=1.0, random_state=RANDOM_STATE)
    reg.fit(X, y)
    return {"mode": "gated", "kind": "hgb", "gate": gate, "loss": loss, "model": reg,
            "columns": list(X.columns), "levels": levels}


def shift_art(gate: float, c: float) -> dict:
    return {"mode": "gated", "kind": "shift", "gate": float(gate), "shift": float(c)}


def cv_select(tab: pd.DataFrame, n_splits: int = 5):
    """5-fold GroupKFold over train events; returns (table rows, best artifact config)."""
    from sklearn.model_selection import GroupKFold

    from src.risk.evaluate import metrics
    folds = list(GroupKFold(n_splits=n_splits).split(tab, groups=tab.index.to_numpy()))
    true_all = tab["target"].to_numpy()

    def score(make_pred):
        oof = np.zeros(len(tab))
        Ls = []
        for tr, te in folds:
            oof[te] = make_pred(tab.iloc[tr], tab.iloc[te])
            Ls.append(metrics(true_all[te], oof[te])["L"])
        pooled = metrics(true_all, oof)
        return float(np.mean(Ls)), pooled["L"], pooled["f2"], pooled["mae"]

    rows, cfgs = [], []

    def add(name, cfg, res):
        rows.append((name, *res))
        cfgs.append(cfg)

    add("naive", None, score(lambda a, b: b["naive_risk"].to_numpy()))
    for g in GATES:
        best = None
        for c in SHIFT_GRID:
            art = shift_art(g, c)
            res = score(lambda a, b, art=art: predict_gated(art, b))
            if best is None or res[0] < best[1][0]:
                best = (c, res)
        add(f"shift gate={g} c={best[0]}", ("shift", g, best[0]), best[1])
        for loss in ("absolute_error", "squared_error"):
            res = score(lambda a, b, g=g, loss=loss: predict_gated(fit_gated(a, g, loss), b))
            add(f"hgb gate={g} {loss}", ("hgb", g, loss), res)
    best_i = min(range(len(rows)), key=lambda i: rows[i][1])
    return rows, cfgs[best_i]


def predict_table(art: dict, tab: pd.DataFrame) -> np.ndarray:
    """Predict final log10 Pc for a feature table (from build_table)."""
    if art.get("mode") == "gated":
        return predict_gated(art, tab)
    X, _ = feature_matrix(tab, levels=art["levels"], floor=art.get("floor"))
    X = X[art["columns"]]
    naive = tab["naive_risk"].to_numpy()
    floor = art.get("floor")
    base = np.clip(naive, floor, None) if floor is not None else naive
    pred = np.clip(base + art["model"].predict(X), -30.0, 0.0)
    clf = art.get("classifier")
    if clf is not None:
        p = clf.predict_proba(X)[:, 1]
        # events the classifier flags as high-risk are lifted to just above the threshold
        pred = np.where(p >= 0.5, np.maximum(pred, HIGH_RISK + 0.1), pred)
    return pred


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", type=float, default=None)
    ap.add_argument("--mode", choices=["residual", "gated"], default="residual")
    ap.add_argument("--classifier", action="store_true")
    ap.add_argument("--out", type=Path, default=MODEL_PATH)
    a = ap.parse_args()
    t0 = time.time()
    train = pd.read_csv(DATA / "train_data.csv")
    labels = usable_labels(train)
    tab = build_table(train[train["event_id"].isin(labels.index)], labels)
    print(f"train events: {len(tab)}, high-risk final: {int((tab['target'] >= HIGH_RISK).sum())}")
    if a.mode == "gated":
        rows, cfg = cv_select(tab)
        print(f"{'config':36}{'meanCV_L':>10}{'pooledL':>10}{'pooledF2':>10}{'pooledMAE':>10}")
        for r in rows:
            print(f"{r[0]:36}{r[1]:10.3f}{r[2]:10.3f}{r[3]:10.3f}{r[4]:10.3f}")
        if cfg is None:
            art = {"mode": "gated", "kind": "shift", "gate": 0.0, "shift": 0.0}  # plain naive
        elif cfg[0] == "shift":
            art = shift_art(cfg[1], cfg[2])
        else:
            art = fit_gated(tab, cfg[1], cfg[2])
        print("chosen:", {k: v for k, v in art.items() if k not in ("model", "columns", "levels")})
    else:
        art = fit(tab, floor=a.floor, with_classifier=a.classifier)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(art, a.out)
    print(f"saved {a.out} ; training time {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
