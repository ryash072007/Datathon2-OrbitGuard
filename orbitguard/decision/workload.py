"""Alert workload at equal safety: how many alerts does an operator review to catch the same high-risk events?

CLI: python -m orbitguard.decision.workload [--root .] [--bootstrap-repeats 1000]

Every policy scores each ESA test event using only CDMs >= 2 days before TCA. Score-based policies (triage
classifier, decision-layer calibrated P(high), optional Snap ML) are thresholded so that their TRAIN
out-of-fold recall equals the naive rule's TRAIN recall; thresholds never see test labels. Test labels are
opened only after the thresholds, scores and artefact SHA-256 values are frozen (read_labels_after_freeze).
Nothing is retrained here: it reuses triage.joblib, decision.joblib and the stored triage OOF predictions.
"""
from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

HIGH_RISK = -6.0
SEED = 20261017
NAIVE = "naive_latest_risk>=-6"
SNAPML_OOF = "snapml_oof.csv"  # artifacts/zai: columns event_id, score (train out-of-fold)
SNAPML_TEST = "snapml_test_scores.csv"  # artifacts/zai: columns event_id, score (frozen model on test inputs)


# ----------------------------------------------------------------------------- pure helpers
def match_recall_threshold(y_high: np.ndarray, score: np.ndarray, target_recall: float) -> float:
    """Highest threshold t such that recall of (score >= t) on (y_high, score) is >= target_recall.

    Called on TRAIN out-of-fold data only. Alerts are score >= t.
    """
    y_high, score = np.asarray(y_high, dtype=bool), np.asarray(score, dtype=float)
    if not y_high.any():
        raise ValueError("No high-risk events to match recall against")
    pos = np.sort(score[y_high])[::-1]
    k = int(np.ceil(target_recall * len(pos) - 1e-12))
    k = min(max(k, 1), len(pos))
    return float(pos[k - 1])


def policy_stats(alert: np.ndarray, high: np.ndarray) -> dict:
    alert, high = np.asarray(alert, dtype=bool), np.asarray(high, dtype=bool)
    n_alert, caught = int(alert.sum()), int((alert & high).sum())
    return {"alerts": n_alert, "caught": caught, "missed": int(high.sum() - caught),
            "false_alerts": n_alert - caught,
            "precision": caught / n_alert if n_alert else 0.0,
            "recall": caught / high.sum() if high.any() else 0.0,
            "alerts_per_caught": n_alert / caught if caught else None}


def paired_bootstrap(alerts: dict, high: np.ndarray, baseline: str, repeats: int, seed: int = SEED) -> dict:
    """Paired bootstrap over events. For each policy: false alerts removed vs baseline, alerts removed,
    recall difference (policy - baseline). Each is reported as point estimate and 95% percentile CI."""
    high = np.asarray(high, dtype=bool)
    n = len(high)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(repeats, n))
    h = high[idx]
    nh = h.sum(axis=1)

    def counts(a):
        a = np.asarray(a, dtype=bool)[idx]
        return a.sum(axis=1), (a & h).sum(axis=1)

    base_alert, base_tp = counts(alerts[baseline])
    base_fp = base_alert - base_tp
    valid = nh > 0
    out = {}
    for name, a in alerts.items():
        if name == baseline:
            continue
        al, tp = counts(a)
        fp = al - tp
        diffs = {"false_alerts_removed": base_fp - fp, "alerts_removed": base_alert - al,
                 "caught_difference": tp - base_tp, "false_alerts_difference": fp - base_fp,
                 "recall_difference": np.where(valid, tp / np.maximum(nh, 1) - base_tp / np.maximum(nh, 1), np.nan)}
        point_base, point = policy_stats(alerts[baseline], high), policy_stats(a, high)
        pts = {"false_alerts_removed": point_base["false_alerts"] - point["false_alerts"],
               "alerts_removed": point_base["alerts"] - point["alerts"],
               "caught_difference": point["caught"] - point_base["caught"],
               "false_alerts_difference": point["false_alerts"] - point_base["false_alerts"],
               "recall_difference": point["recall"] - point_base["recall"]}
        out[name] = {k: {"point": float(pts[k]),
                         "ci95": [float(x) for x in np.nanquantile(v[valid], [0.025, 0.975])],
                         "repeats": int(valid.sum())} for k, v in diffs.items()}
    return out


def summary_line(rows: dict, boot: dict, target_recall: float, n_test: int, n_high: int) -> str:
    """Plain-English summary generated from the measured numbers (nothing hand-typed)."""
    base = rows[NAIVE]
    ci = lambda d: f"95% CI {d['ci95'][0]:.0f} to {d['ci95'][1]:.0f}"
    parts = [f"On {n_test} ESA test events ({n_high} high-risk) the naive rule raises {base['alerts']} alerts, "
             f"catching {base['caught']} (recall {base['recall']:.3f})."]
    budgets = {k: b for k, b in boot.items() if k.startswith("budget:")}
    better = [k for k, b in budgets.items() if b["caught_difference"]["ci95"][0] > 0]
    if budgets and not better:
        parts.append("ML does not reduce workload at equal budget: with the same number of alerts, "
                     + "; ".join(f"{k[7:]} catches {rows[k]['caught'] - base['caught']:+d} events "
                                 f"({ci(b['caught_difference'])})" for k, b in budgets.items()) + ".")
    elif better:
        parts.append("At equal budget, ML catches significantly more events: "
                     + "; ".join(f"{k[7:]} {boot[k]['caught_difference']['point']:+.0f} "
                                 f"({ci(boot[k]['caught_difference'])})" for k in better) + ".")
    cands = [k for k in boot if k != NAIVE]
    if cands:
        best = max(cands, key=lambda k: (rows[k]["recall"], -rows[k]["alerts"]))
        b, r = boot[best], rows[best]
        miss = -b["caught_difference"]["point"]
        ci_miss = [-b["caught_difference"]["ci95"][1], -b["caught_difference"]["ci95"][0]]
        parts.append(f"Best safety-first row is {best} (recall {r['recall']:.3f}): missed events change by "
                     f"{miss:+.0f} (95% CI {ci_miss[0]:.0f} to {ci_miss[1]:.0f}) at a cost of "
                     f"{-b['alerts_removed']['point']:+.0f} alerts and {b['false_alerts_difference']['point']:+.0f} "
                     f"false alerts ({ci(b['false_alerts_difference'])}).")
    parts.append(f"Score thresholds were matched to the naive train recall {target_recall:.3f} using train data only.")
    return " ".join(parts)


def top_k_alert(score: np.ndarray, k: int) -> np.ndarray:
    """Alert on the k highest-scoring events (stable order on ties)."""
    order = np.argsort(-np.asarray(score, dtype=float), kind="stable")[:k]
    a = np.zeros(len(score), dtype=bool)
    a[order] = True
    return a


RANK_BUDGETS = (50, 100, 250)


def run_workload(train_sets: dict, test_scores: dict, test_ids: np.ndarray, naive_test_alert: np.ndarray,
                 act_alerts: dict, target_recall: float, label_reader: Callable[[], pd.Series],
                 repeats: int = 1000, naive_score: np.ndarray | None = None) -> dict:
    """Core, label-free until the end.

    train_sets: name -> (y_high_oof bool, oof_score). test_scores: name -> test score array aligned with test_ids.
    act_alerts: name -> bool alert array (decision-layer action rules, no threshold to tune).
    label_reader(): returns Series true_risk indexed by event_id; called exactly once, after thresholds are set.
    """
    thresholds, matched_alerts = {}, {}
    for name, (y, s) in train_sets.items():
        if name not in test_scores:
            continue
        t = match_recall_threshold(y, s, target_recall)
        thresholds[name] = {"threshold": t,
                            "train_oof_recall": float(((s >= t) & y).sum() / y.sum()),
                            "train_oof_alerts": int((s >= t).sum()), "train_events": int(len(y)),
                            "source": "train out-of-fold scores, recall matched to naive train recall"}
        matched_alerts[f"matched:{name}"] = np.asarray(test_scores[name]) >= t
    # Budget K = number of naive test alerts: unlabelled operator capacity, no labels involved.
    k_budget = int(np.asarray(naive_test_alert, dtype=bool).sum())
    budget_alerts = {f"budget:{n}": top_k_alert(v, k_budget) for n, v in test_scores.items() if n in train_sets}
    alerts = {NAIVE: np.asarray(naive_test_alert, dtype=bool), **{k: np.asarray(v, dtype=bool) for k, v in act_alerts.items()},
              **matched_alerts, **budget_alerts}
    # ---- thresholds and alerts are fixed; labels open only now
    labels = label_reader()
    missing = set(test_ids) - set(labels.index)
    if missing:
        raise ValueError(f"{len(missing)} test events have no released label")
    high = labels.loc[test_ids].to_numpy(dtype=float) >= HIGH_RISK
    rows = {k: policy_stats(a, high) for k, a in alerts.items()}
    boot = paired_bootstrap(alerts, high, NAIVE, repeats)
    for k, b in boot.items():
        cd = b["caught_difference"]["point"]
        extra = rows[k]["alerts"] - rows[NAIVE]["alerts"]
        b["extra_reviews_per_extra_caught"] = (float(extra / cd) if cd > 0 else None)
        b["extra_reviews_note"] = "extra alerts vs naive / extra caught events; only defined where caught difference > 0"
    ranking = {}
    budgets = sorted(set(RANK_BUDGETS) | {k_budget})
    rankers = {**({"naive_latest_risk": naive_score} if naive_score is not None else {}), **test_scores}
    for n, v in rankers.items():
        ranking[n] = {str(k): int((top_k_alert(v, k) & high).sum()) for k in budgets}
    return {"alert_budget_k": k_budget, "ranking_caught_at_budget": ranking, "budgets": budgets,
            "n_high_risk_test_for_ranking": int(high.sum()), "thresholds": thresholds, "policies": rows, "paired_bootstrap_vs_naive": boot,
            "n_test_events": int(len(high)), "n_high_risk_test": int(high.sum()),
            "summary": summary_line(rows, boot, target_recall, len(high), int(high.sum()))}


# ----------------------------------------------------------------------------- real-data plumbing
def _sha256(path: Path) -> str:
    from orbitguard.ml.data import digest
    return digest(path)


def _optional_snapml(root: Path, train_ids: np.ndarray, train_y: pd.Series, test_ids: np.ndarray):
    d = root / "artifacts" / "zai"
    oof, tst = d / SNAPML_OOF, d / SNAPML_TEST
    if not (oof.exists() and tst.exists()):
        return None
    o = pd.read_csv(oof).set_index("event_id")["score"]
    t = pd.read_csv(tst).set_index("event_id")["score"]
    if not set(train_ids) <= set(o.index) or not set(test_ids) <= set(t.index):
        raise ValueError("Snap ML score files do not cover the train/test events")
    return (train_y.loc[train_ids].to_numpy(dtype=bool), o.loc[train_ids].to_numpy(dtype=float)), \
        t.loc[test_ids].to_numpy(dtype=float), [oof, tst]


def run(root: Path, repeats: int = 1000) -> dict:
    import joblib

    from orbitguard.decision import decision as dec
    from orbitguard.decision.features import build_table
    from orbitguard.decision.train import usable_labels
    from orbitguard.ml.data import read_labels_after_freeze
    from orbitguard.ml.model import feature_frame
    from orbitguard.ml.triage import predict_triage

    base = root / "artifacts" / "ml"
    data = base / "data"
    need = [base / "triage.joblib", base / "triage_training_oof.csv", base / "decision.joblib",
            data / "train_data.csv", data / "test_data.csv"]
    for p in need:
        if not p.exists():
            raise FileNotFoundError(f"{p} missing: run `orbitguard train-triage` and `orbitguard decision-fit` first")
    used = list(need)
    train_raw = pd.read_csv(data / "train_data.csv")
    test_raw = pd.read_csv(data / "test_data.csv")

    # ---- train side: naive recall and out-of-fold scores
    labels_tr = usable_labels(train_raw)
    ttab = build_table(train_raw[train_raw["event_id"].isin(labels_tr.index)], labels_tr)
    y_tr = pd.Series(ttab["target"].to_numpy() >= HIGH_RISK, index=ttab.index)
    target_recall = float(((ttab["naive_risk"] >= HIGH_RISK) & y_tr).sum() / y_tr.sum())
    train_sets = {}
    tri = pd.read_csv(base / "triage_training_oof.csv").set_index("event_id")
    train_sets["triage_classifier"] = (tri["high_risk_target"].to_numpy(dtype=bool),
                                       tri["triage_score"].to_numpy(dtype=float))
    folds = dec._folds(ttab)
    train_sets["decision_p_high"] = (y_tr.to_numpy(), dec.oof_proba(ttab, folds))

    # ---- test side: inputs only (>= 2 d before TCA), no labels
    test_tab = build_table(test_raw)
    test_ids = test_tab.index.to_numpy()
    art = joblib.load(base / "decision.joblib")
    action, _, p_high = dec.actions_table(art, test_tab)
    tri_model = joblib.load(base / "triage.joblib")
    ids2, records, _ = feature_frame(test_raw)
    tri_score = pd.Series(predict_triage(tri_model, records), index=ids2).loc[test_ids].to_numpy()
    test_scores = {"triage_classifier": tri_score, "decision_p_high": p_high}
    snap = _optional_snapml(root, ttab.index.to_numpy(), y_tr, test_ids)
    if snap is not None:
        train_sets["snapml"], test_scores["snapml"] = snap[0], snap[1]
        used += snap[2]
    act_alerts = {"decision_action==ACT": action == "ACT", "decision_action in (ACT,WAIT)": action != "MONITOR"}
    naive_alert = test_tab["naive_risk"].to_numpy(dtype=float) >= HIGH_RISK

    # ---- freeze: hash every artefact before labels
    before = {str(p.relative_to(root)): _sha256(p) for p in used}
    res = run_workload(train_sets, test_scores, test_ids, naive_alert, act_alerts, target_recall,
                       lambda: read_labels_after_freeze(root, base / "decision.joblib").set_index("event_id")["true_risk"],
                       repeats, naive_score=test_tab["naive_risk"].to_numpy(dtype=float))
    after = {str(p.relative_to(root)): _sha256(p) for p in used}
    if before != after:
        raise ValueError("An artefact changed during workload evaluation; no evidence written")
    evidence = {
        "status": "ready", "source": "ESA Collision Avoidance Challenge test set; sealed released labels",
        "question": "At the naive rule's recall of high-risk events, how many alerts and false alarms remain?",
        "target_recall_naive_train": target_recall, **res,
        "method": ["Every policy scores each test event using only CDMs with time_to_tca >= 2 days.",
                   "naive: alert if latest reported risk >= -6.",
                   "decision layer: alert if action == ACT; second row ACT or WAIT (everything but MONITOR).",
                   "matched:*: score thresholded at the highest value whose TRAIN out-of-fold recall >= the naive "
                   "rule's TRAIN recall. Triage uses stored triage_training_oof.csv; decision P(high) uses "
                   "5-fold GroupKFold out-of-fold predictions refit here. No test label is used for thresholds.",
                   "budget:*: alert on the top-K test events by each score, K = number of alerts the naive rule raises "
                   "on the test inputs. K is the operator's alert capacity and comes from unlabelled inputs only. "
                   "ranking_caught_at_budget lists high-risk events caught in the top K for K in budgets; naive is "
                   "ranked by latest risk (ties broken by input order).",
                   "Paired bootstrap over test events (same resample for all policies), 95% percentile CI.",
                   "Snap ML policy included only if artifacts/zai/snapml_oof.csv and snapml_test_scores.csv exist."],
        "snapml_included": snap is not None,
        "bootstrap_repeats": repeats,
        "fingerprints": {"sha256_before_labels": before, "sha256_after_evaluation": after},
        "platform": {"hostname": socket.gethostname(), "machine": platform.machine(),
                     "byteorder": sys.byteorder, "python": platform.python_version()},
        "evaluated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "limitations": ["ESA selected encounters over-represent high-risk events; alert counts do not estimate "
                        "operational volumes.",
                        "Test set is a retrospective public set used by earlier project versions.",
                        "Realised test recall differs from the naive recall because thresholds come from train."],
    }
    from orbitguard.ml.data import write_json
    write_json(base / "workload_evidence.json", evidence)
    return evidence


def _print_table(ev: dict) -> None:
    print(f"{'policy':36}{'alerts':>8}{'caught':>8}{'missed':>8}{'false':>8}{'prec':>8}{'recall':>8}{'al/catch':>10}")
    for k, r in ev["policies"].items():
        apc = f"{r['alerts_per_caught']:.2f}" if r["alerts_per_caught"] else "n/a"
        print(f"{k:36}{r['alerts']:8d}{r['caught']:8d}{r['missed']:8d}{r['false_alerts']:8d}"
              f"{r['precision']:8.3f}{r['recall']:8.3f}{apc:>10}")
    for k, b in ev["paired_bootstrap_vs_naive"].items():
        c, f = b["caught_difference"], b["false_alerts_difference"]
        e = b["extra_reviews_per_extra_caught"]
        print(f"{k}: caught diff {c['point']:+.0f} ({c['ci95'][0]:.0f} to {c['ci95'][1]:.0f}); "
              f"false-alert diff {f['point']:+.0f} ({f['ci95'][0]:.0f} to {f['ci95'][1]:.0f}); "
              f"extra reviews per extra caught {'n/a' if e is None else f'{e:.2f}'}")
    print("caught at budget K: " + ", ".join(f"K={k}" for k in ev["budgets"]))
    for n, v in ev["ranking_caught_at_budget"].items():
        print(f"  {n:24}" + "".join(f"{v[str(k)]:8d}" for k in ev["budgets"]))
    print(ev["summary"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--bootstrap-repeats", type=int, default=1000)
    a = ap.parse_args()
    _print_table(run(a.root.resolve(), a.bootstrap_repeats))


if __name__ == "__main__":
    main()
