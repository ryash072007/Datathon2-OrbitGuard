"""Baseline-preserving learned escalation, selected without test-label tuning."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.model_selection import StratifiedKFold
from threadpoolctl import threadpool_limits

from .accuracy import audit_metrics
from .data import digest, paths, read_labels, write_json
from .model import SEED, _estimator, _xy, cv_predict, feature_frame, predict


def _vectors(latest, learned):
    latest, learned = np.asarray(latest, dtype=float), np.asarray(learned, dtype=float)
    if latest.ndim != 1 or latest.shape != learned.shape or not len(latest) or not np.isfinite(latest).all() or not np.isfinite(learned).all():
        raise ValueError('Latest and learned forecasts must be matching finite vectors')
    return latest, learned


def guard_predictions(latest, learned, policy):
    latest, learned = _vectors(latest, learned)
    threshold = policy['threshold']
    if threshold is None:
        return latest.copy()
    value = policy['escalated_log10_pc']
    if not np.isfinite(threshold) or not np.isfinite(value) or not -6 <= value <= 0:
        raise ValueError('Guard thresholds and escalated forecasts must be finite valid values')
    return np.where((latest < -6) & (learned >= threshold), value, latest)


def choose_guard(actual, latest, learned, false_positive_ratio=1.25):
    latest, learned = _vectors(latest, learned)
    actual = np.asarray(actual, dtype=bool)
    if actual.shape != latest.shape or not np.isfinite(false_positive_ratio) or false_positive_ratio < 1:
        raise ValueError('Outcomes must match forecasts and the false-positive ratio must be at least one')
    baseline = latest >= -6
    true_positive = int((actual & baseline).sum())
    false_positive = int((~actual & baseline).sum())
    positive_count = int(actual.sum())
    budget = int(np.floor(false_positive * false_positive_ratio))

    def outcome(threshold, positives, false_alarms):
        missed = positive_count - positives
        denominator = 5 * positives + 4 * missed + false_alarms
        return {'threshold': threshold, 'metrics': {'tp': positives, 'fp': false_alarms, 'fn': missed,
                'tn': len(actual) - positive_count - false_alarms,
                'recall': positives / positive_count if positive_count else 0.,
                'precision': positives / (positives + false_alarms) if positives + false_alarms else 0.,
                'f2': 5 * positives / denominator if denominator else 0.}}

    choices = [outcome(None, true_positive, false_positive)]
    order = np.flatnonzero(~baseline)
    order = order[np.argsort(-learned[order], kind='stable')]
    added_positive = np.cumsum(actual[order])
    added_false = np.cumsum(~actual[order])
    for index in range(len(order)):
        if index + 1 < len(order) and learned[order[index]] == learned[order[index + 1]]:
            continue
        false_alarms = false_positive + int(added_false[index])
        if false_alarms > budget:
            break
        choices.append(outcome(float(learned[order[index]]), true_positive + int(added_positive[index]), false_alarms))
    selected = max(choices, key=lambda choice: (choice['metrics']['f2'], -choice['metrics']['fp']))
    return {**selected, 'false_positive_budget': budget, 'false_positive_ratio': false_positive_ratio}


def _escalated_value(target, latest):
    high_risk = target[target >= -6]
    missed = target[(target >= -6) & (latest < -6)]
    if not len(high_risk):
        raise ValueError('High-risk training examples are required')
    return float((missed.sum() + 10 * high_risk.mean()) / (len(missed) + 10))


def _fit_predict(records, latest, target, training, validation, metadata):
    vectorizer = DictVectorizer(sparse=False)
    training_features = vectorizer.fit_transform([records[index] for index in training])
    estimator = _estimator(metadata['hyperparameters'])
    estimator.fit(training_features, np.clip(target[training], -12, 0) - np.clip(latest[training], -12, 0),
                  sample_weight=np.where(target[training] >= -6, metadata['hyperparameters']['high_risk_weight'], 1))
    correction = estimator.predict(vectorizer.transform([records[index] for index in validation]))
    return np.minimum(latest[validation] + metadata['learned_alpha'] * correction, 0)


def train_guard(root):
    base, data = paths(root)
    model_path = base / 'model.joblib'
    metadata = json.loads((base / 'model_metadata.json').read_text())
    model_hash = digest(model_path)
    identifiers, records, latest, target = _xy(pd.read_csv(data / 'train_data.csv'))
    nested = latest.copy()
    simple = latest.copy()
    folds = []
    with threadpool_limits(limits=1):
        for fold, (training, validation) in enumerate(StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED + 1).split(latest, target >= -6)):
            inner_correction = cv_predict([records[index] for index in training], latest[training], target[training], metadata['hyperparameters'])
            inner_forecast = np.minimum(latest[training] + metadata['learned_alpha'] * inner_correction, 0)
            policy = choose_guard(target[training] >= -6, latest[training], inner_forecast)
            policy['escalated_log10_pc'] = _escalated_value(target[training], latest[training])
            learned = _fit_predict(records, latest, target, training, validation, metadata)
            nested[validation] = guard_predictions(latest[validation], learned, policy)
            simple_policy = choose_guard(target[training] >= -6, latest[training], latest[training])
            simple_policy['escalated_log10_pc'] = policy['escalated_log10_pc']
            simple[validation] = guard_predictions(latest[validation], latest[validation], simple_policy)
            folds.append({'fold': fold, 'training_events': len(training), 'validation_events': len(validation),
                          'policy': policy, 'simple_policy': simple_policy})
            print(f'Nested escalation fold {fold + 1}/3 complete', flush=True)
        correction = cv_predict(records, latest, target, metadata['hyperparameters'])
    learned = np.minimum(latest + metadata['learned_alpha'] * correction, 0)
    policy = choose_guard(target >= -6, latest, learned)
    policy['escalated_log10_pc'] = _escalated_value(target, latest)
    simple_policy = choose_guard(target >= -6, latest, latest)
    simple_policy['escalated_log10_pc'] = policy['escalated_log10_pc']
    frozen = {'status': 'experimental', 'method': 'baseline_preserving_residual_guard', **policy,
              'frozen_at': datetime.now(timezone.utc).isoformat(), 'final_test_labels_accessed': False,
              'baseline_model_sha256': model_hash, 'training_data_sha256': digest(data / 'train_data.csv'),
              'prediction_source_sha256': digest(Path(__file__).with_name('model.py')),
              'guard_source_sha256': digest(Path(__file__)),
              'selection_rule': 'Maximum training-event OOF F2, preserving every baseline alert, with at most 25% more training-validation false positives; ties prefer fewer false positives.',
              'forecast_rule': 'Preserve latest risk except learned escalations. Escalated value is the mean later log risk of baseline-missed high-risk training events, shrunk toward the overall high-risk training mean with 10 pseudo-observations.',
              'fixed_prior_model': {'hyperparameters': metadata['hyperparameters'], 'learned_alpha': metadata['learned_alpha']},
              'simple_policy': simple_policy,
              'nested_validation': {'baseline': audit_metrics(target, latest), 'guard': audit_metrics(target, nested),
                                    'simple_threshold': audit_metrics(target, simple), 'folds': folds,
                                    'limitation': 'Outer event folds isolate new threshold/calibration selection. Base hyperparameters were selected by an earlier development cycle, so this is development evidence, not a new blind evaluation.'},
              'default_changed': False}
    if digest(model_path) != model_hash:
        raise ValueError('Base model changed while fitting escalation policy')
    write_json(base / 'guard_policy.json', frozen)
    return frozen


def evaluate_guard(root, bootstrap_repeats=1000):
    base, data = paths(root)
    policy_path = base / 'guard_policy.json'
    if not policy_path.exists():
        raise ValueError('Freeze the guard policy before evaluation')
    policy = json.loads(policy_path.read_text())
    policy_hash = digest(policy_path)
    model_hash = digest(base / 'model.joblib')
    if (model_hash != policy['baseline_model_sha256'] or digest(Path(__file__)) != policy['guard_source_sha256']
            or digest(Path(__file__).with_name('model.py')) != policy['prediction_source_sha256']):
        raise ValueError('Frozen guard or base model changed; train the policy again')
    model = joblib.load(base / 'model.joblib')
    identifiers, records, latest = feature_frame(pd.read_csv(data / 'test_data.csv'))
    learned = predict(model, records, latest, learned=True)
    forecast = guard_predictions(latest, learned, policy)
    simple_forecast = guard_predictions(latest, latest, policy['simple_policy'])
    labels = read_labels(root).set_index('event_id')
    if set(identifiers) != set(labels.index):
        raise ValueError('Test input and released-label sets differ')
    target = labels.loc[identifiers, 'true_risk'].to_numpy(dtype=float)
    generator = np.random.default_rng(SEED)
    loss_differences, recall_differences, f2_differences = [], [], []
    for _ in range(bootstrap_repeats):
        indices = generator.integers(0, len(target), len(target))
        baseline_metrics = audit_metrics(target[indices], latest[indices])
        guard_metrics = audit_metrics(target[indices], forecast[indices])
        if baseline_metrics['challenge_loss'] is not None and guard_metrics['challenge_loss'] is not None:
            loss_differences.append(guard_metrics['challenge_loss'] - baseline_metrics['challenge_loss'])
        if (target[indices] >= -6).any():
            recall_differences.append(guard_metrics['recall'] - baseline_metrics['recall'])
        f2_differences.append(guard_metrics['f2'] - baseline_metrics['f2'])
    interval = lambda values: np.quantile(values, [.025, .975]).tolist() if values else None
    if digest(policy_path) != policy_hash or digest(base / 'model.joblib') != model_hash:
        raise ValueError('Frozen artifacts changed during evaluation')
    report = {'status': 'experimental', 'evaluation_role': 'retrospective_recheck',
              'generated_at': datetime.now(timezone.utc).isoformat(), 'policy': policy,
              'methods': {'latest_baseline': audit_metrics(target, latest), 'residual_guard': audit_metrics(target, forecast),
                          'simple_threshold': audit_metrics(target, simple_forecast)},
              'paired_bootstrap': {'repeats': bootstrap_repeats, 'loss_difference_ci95': interval(loss_differences),
                                   'recall_difference_ci95': interval(recall_differences), 'f2_difference_ci95': interval(f2_differences)},
              'additional_alert_event_ids': identifiers[(latest < -6) & (forecast >= -6)].astype(str).tolist(),
              'additional_high_risk_events_detected': int(((latest < -6) & (forecast >= -6) & (target >= -6)).sum()),
              'fingerprints': {'policy_before_labels': policy_hash, 'policy_after': digest(policy_path), 'base_model': model_hash},
              'limitations': ['This public test set was already evaluated by prior project versions; it is not a blind test.',
                              'The forecast target is later reported risk, not an observed collision.',
                              'The training false-positive budget is not a guarantee on future data.',
                              'New alerts must be reviewed by an operator; this does not command a spacecraft.']}
    write_json(base / 'guard_evidence.json', report)
    return report
