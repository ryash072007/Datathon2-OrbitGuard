"""Training-only forecast experiment and transparent retrospective accuracy audit."""

from __future__ import annotations

from datetime import datetime, timezone
import platform
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import StratifiedKFold

from .data import digest, load_frames, paths, read_labels, write_json
from .model import SEED, _xy, clipped, feature_frame, metrics, predict


def shrink_risk(latest, coefficient):
    values = np.asarray(latest, dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(coefficient) or not 0 < coefficient <= 1:
        raise ValueError("Shrinkage requires finite risks and a coefficient in (0, 1].")
    return np.where(values >= -6, -6 + coefficient * (values + 6), values)


def fit_shrinkage(latest, targets):
    latest = np.asarray(latest, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if latest.shape != targets.shape or not np.isfinite(latest).all() or not np.isfinite(targets).all():
        raise ValueError("Training risks and targets must be matching finite arrays.")
    eligible = (latest >= -6) & (targets >= -6)
    predictor = latest[eligible] + 6
    target = targets[eligible] + 6
    denominator = float(predictor @ predictor)
    return float(np.clip(predictor @ target / denominator, .01, 1)) if denominator else 1.


def _wilson(successes, count):
    if not count:
        return None
    critical = 1.959963984540054
    fraction = successes / count
    denominator = 1 + critical ** 2 / count
    center = (fraction + critical ** 2 / (2 * count)) / denominator
    half = critical * np.sqrt(fraction * (1 - fraction) / count + critical ** 2 / (4 * count ** 2)) / denominator
    return [max(0., float(center - half)), min(1., float(center + half))]


def classification_intervals(actual, estimated):
    actual, estimated = np.asarray(actual, dtype=bool), np.asarray(estimated, dtype=bool)
    true_positive = int((actual & estimated).sum())
    return {"method": "Wilson score, 95%, event-level binomial intervals",
            "recall_ci95": _wilson(true_positive, int(actual.sum())),
            "precision_ci95": _wilson(true_positive, int(estimated.sum()))}


def audit_metrics(targets, predictions):
    targets, predictions = np.asarray(targets, dtype=float), np.asarray(predictions, dtype=float)
    score = metrics(targets, clipped(predictions))
    actual, estimated = targets >= -6, predictions >= -6
    return {**score, "log10_mae": float(np.mean(np.abs(predictions - targets))),
            "log10_rmse": float(np.sqrt(np.mean((predictions - targets) ** 2))),
            "classification_accuracy": float(np.mean(actual == estimated)),
            "always_low_risk_accuracy": float(np.mean(~actual)),
            "confusion_matrix": dict(zip(("true_positive", "false_positive", "false_negative", "true_negative"),
                                         (score[key] for key in ("tp", "fp", "fn", "tn")))),
            **classification_intervals(actual, estimated)}


def _loss_difference_interval(targets, baseline, challenger, repeats):
    generator = np.random.default_rng(SEED)
    differences = []
    for _ in range(repeats):
        indices = generator.integers(0, len(targets), len(targets))
        reference = metrics(targets[indices], clipped(baseline[indices]))["challenge_loss"]
        candidate = metrics(targets[indices], clipped(challenger[indices]))["challenge_loss"]
        if reference is not None and candidate is not None:
            differences.append(candidate - reference)
    return {"repeats": repeats, "valid_repeats": len(differences),
            "quantity": "challenger minus latest-risk baseline ESA loss; negative favours challenger",
            "ci95": np.quantile(differences, [.025, .975]).tolist() if differences else None}


def audit_accuracy(root, bootstrap_repeats=1000):
    if bootstrap_repeats < 1:
        raise ValueError("bootstrap_repeats must be positive")
    base, _ = paths(root)
    train, test = load_frames(root)
    _, _, latest, targets = _xy(train)
    out_of_fold = np.empty(len(targets))
    folds = []
    for training, validation in StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED).split(latest, targets >= -6):
        coefficient = fit_shrinkage(latest[training], targets[training])
        out_of_fold[validation] = shrink_risk(latest[validation], coefficient)
        folds.append({"coefficient": coefficient, "train_events": len(training), "validation_events": len(validation)})
    frozen = {"method": "high_risk_shrinkage", "coefficient": fit_shrinkage(latest, targets),
              "source": "official training events only", "training_data_sha256": digest(base / "data/train_data.csv"),
              "frozen_at": datetime.now(timezone.utc).isoformat(), "seed": SEED,
              "rule": "Least-squares slope toward log10 Pc=-6, fitted only on high-risk training targets with high-risk latest values. Low-risk forecasts and all alert decisions are preserved.",
              "default_changed": False, "status": "experimental",
              "cv_baseline": audit_metrics(targets, latest), "cv_challenger": audit_metrics(targets, out_of_fold),
              "cv_loss_difference": _loss_difference_interval(targets, latest, out_of_fold, bootstrap_repeats),
              "folds": folds}
    parameter_path = base / "risk_shrinkage.json"
    write_json(parameter_path, frozen)
    frozen_hash = digest(parameter_path)
    model_hash = digest(base / "model.joblib")
    model = joblib.load(base / "model.joblib")
    event_ids, test_records, test_latest = feature_frame(test)
    predictions = {"latest_baseline": test_latest,
                   "learned_residual": predict(model, test_records, test_latest, learned=True),
                   "high_risk_shrinkage": shrink_risk(test_latest, frozen["coefficient"])}
    labels = read_labels(root).set_index("event_id")
    if set(event_ids) != set(labels.index):
        raise ValueError("Test input and released-label event sets differ")
    truth = labels.loc[event_ids, "true_risk"].to_numpy(dtype=float)
    methods = {name: audit_metrics(truth, forecast) for name, forecast in predictions.items()}
    bootstrap = _loss_difference_interval(truth, test_latest, predictions["high_risk_shrinkage"], bootstrap_repeats)
    missed = (truth >= -6) & (test_latest < -6)
    false_alarms = (truth < -6) & (test_latest >= -6)
    review = np.argsort(-np.abs(test_latest - truth), kind="stable")[:10]
    report = {"status": "ready", "generated_at": datetime.now(timezone.utc).isoformat(),
              "architecture": platform.machine(), "evaluation_role": "retrospective_recheck",
              "test_events": len(truth), "high_risk_events": int((truth >= -6).sum()),
              "methods": methods, "shrinkage": frozen, "shrinkage_loss_difference": bootstrap,
              "fingerprints": {"model_before": model_hash, "model_after": digest(base / "model.joblib"),
                               "challenger_before_labels": frozen_hash, "challenger_after": digest(parameter_path),
                               "test_inputs_sha256": digest(base / "data/test_data.csv"),
                               "prediction_source_sha256": digest(Path(__file__).with_name("model.py"))},
              "baseline_missed_event_ids": event_ids[missed].astype(str).tolist(),
              "baseline_false_alarm_event_ids": event_ids[false_alarms].astype(str).tolist(),
              "largest_baseline_errors": [{"event_id": str(event_ids[index]), "latest_log10_pc": float(test_latest[index]),
                                           "final_log10_pc": float(truth[index]), "absolute_log10_error": float(abs(test_latest[index] - truth[index]))}
                                          for index in review],
              "interpretation": ["The target is a later ESA risk estimate, not an observed collision.",
                                 "Overall accuracy is dominated by low-risk events; compare recall, precision, missed alerts, and ESA loss.",
                                 "Intervals quantify sampling uncertainty, not deployment guarantees or collision-probability calibration.",
                                 "The public test set was evaluated by earlier project versions; this is a retrospective recheck, not a new blind test.",
                                 "The shrinkage candidate is trained and frozen before released labels are loaded, is experimental, and does not replace the default.",
                                 "Training folds choose coefficients independently; pooled CV uncertainty does not account for every model-development choice."]}
    write_json(base / "accuracy_audit.json", report)
    return report
