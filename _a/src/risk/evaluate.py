"""Evaluate naive vs model on the ESA test set: python -m src.risk.evaluate"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.risk.features import build_table
from src.risk.train import DATA, HIGH_RISK, MODEL_PATH, ROOT, predict_table


def metrics(true: np.ndarray, pred: np.ndarray) -> dict:
    hr = true >= HIGH_RISK
    pr = pred >= HIGH_RISK
    # MSE over true high-risk events, predictions clipped below at -6.001
    mse_hr = float(np.mean((np.clip(pred[hr], -6.001, None) - true[hr]) ** 2)) if hr.any() else float("nan")
    tp = int((hr & pr).sum())
    prec = tp / pr.sum() if pr.sum() else 0.0
    rec = tp / hr.sum() if hr.sum() else 0.0
    f2 = 5 * prec * rec / (4 * prec + rec) if (4 * prec + rec) > 0 else 0.0
    # ESA challenge metric L = MSE_HR / F2 (lower is better). Check the exact definition
    # against arXiv 2008.03069; this is our reading of it.
    return {"L": mse_hr / f2 if f2 > 0 else float("inf"), "mse_hr": mse_hr, "f2": f2,
            "precision": prec, "recall": rec, "mae": float(np.mean(np.abs(pred - true))),
            "n_high_risk": int(hr.sum()), "n_pred_high_risk": int(pr.sum())}


def evaluate(model_path: Path) -> dict:
    test = pd.read_csv(DATA / "test_data.csv")
    priv = pd.read_csv(DATA / "test_data_private.csv").set_index("event_id")["true_risk"]
    tab = build_table(test, priv)
    art = joblib.load(model_path)
    true = tab["target"].to_numpy()
    return {"naive": metrics(true, tab["naive_risk"].to_numpy()),
            "model": metrics(true, predict_table(art, tab)), "n_events": len(tab)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=MODEL_PATH)
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "risk_metrics.json")
    a = ap.parse_args()
    res = evaluate(a.model)
    print(f"{'':8}" + "".join(f"{k:>17}" for k in res["naive"]))
    for name in ("naive", "model"):
        print(f"{name:8}" + "".join(f"{v:17.3f}" for v in res[name].values()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
