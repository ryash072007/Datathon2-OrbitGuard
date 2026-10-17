"""Experimental ranking of later high-risk estimates, separate from collision Pc."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import time

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.model_selection import StratifiedKFold
from threadpoolctl import threadpool_limits

from .data import digest, paths, read_labels, write_json
from .model import SEED, _xy, feature_frame

SCORE_MEANING = 'Model score for probability that the final risk estimate is at least 1e-6; not collision probability Pc. Scores are not calibrated.'


def triage_metrics(actual, scores, threshold):
    actual = np.asarray(actual, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    if not len(actual) or actual.shape != scores.shape or not np.isfinite(scores).all():
        raise ValueError('Matching finite scores and outcomes are required')
    estimated = scores >= threshold
    true_positive = int((actual & estimated).sum())
    false_positive = int((~actual & estimated).sum())
    false_negative = int((actual & ~estimated).sum())
    true_negative = int((~actual & ~estimated).sum())
    denominator = 5 * true_positive + 4 * false_negative + false_positive
    order = np.argsort(-scores, kind='stable')[:max(1, int(np.ceil(len(actual) * .1)))]
    return {'average_precision': float(average_precision_score(actual, scores)) if actual.any() else None,
            'top_10_percent_recall': float(actual[order].sum() / actual.sum()) if actual.any() else 0.,
            'precision': true_positive / max(1, true_positive + false_positive),
            'recall': true_positive / max(1, true_positive + false_negative),
            'f2': 5 * true_positive / denominator if denominator else 0.,
            'tp': true_positive, 'fp': false_positive, 'fn': false_negative, 'tn': true_negative,
            'threshold': float(threshold), 'event_count': len(actual), 'high_risk_event_count': int(actual.sum())}


def choose_threshold(actual, scores):
    precision, recall, thresholds = precision_recall_curve(actual, scores)
    denominator = 4 * precision[:-1] + recall[:-1]
    f2 = np.divide(5 * precision[:-1] * recall[:-1], denominator,
                   out=np.zeros_like(denominator), where=denominator > 0)
    return float(thresholds[int(np.argmax(f2))])


def _classifier(config):
    return HistGradientBoostingClassifier(max_iter=100, learning_rate=.05,
        max_leaf_nodes=config['max_leaf_nodes'], min_samples_leaf=config['min_samples_leaf'],
        l2_regularization=10, early_stopping=False, random_state=SEED)


def predict_triage(model, records):
    with threadpool_limits(limits=1):
        scores = model['estimator'].predict_proba(model['vectorizer'].transform(records))[:, 1]
    return np.clip(scores, 0, 1)


def train_triage(root, configs=None, search_trials=None):
    started = time.perf_counter()
    base, data = paths(root)
    train = pd.read_csv(data / 'train_data.csv')
    ids, records, latest, target = _xy(train)
    actual = target >= -6
    if actual.sum() < 3 or (~actual).sum() < 3:
        raise ValueError('Three-fold triage requires at least three events per class')
    if configs is None:
        configs = [dict(zip(('max_leaf_nodes', 'min_samples_leaf', 'positive_weight'), values))
                   for values in itertools.product([7, 15], [20, 50], [1, 10])]
    if not configs:
        raise ValueError('At least one triage configuration is required')
    folds = []
    for train_index, validation_index in StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED).split(ids, actual):
        vectorizer = DictVectorizer(sparse=False)
        train_features = vectorizer.fit_transform([records[index] for index in train_index])
        validation_features = vectorizer.transform([records[index] for index in validation_index])
        folds.append((train_index, validation_index, train_features, validation_features))
    trials = []
    best = None
    with threadpool_limits(limits=1):
        for config in configs:
            scores = np.empty(len(actual))
            for train_index, validation_index, train_features, validation_features in folds:
                estimator = _classifier(config)
                estimator.fit(train_features, actual[train_index],
                    sample_weight=np.where(actual[train_index], config['positive_weight'], 1))
                scores[validation_index] = estimator.predict_proba(validation_features)[:, 1]
            threshold = choose_threshold(actual, scores)
            result = {'config': config, 'metrics': triage_metrics(actual, scores, threshold)}
            trials.append(result)
            if best is None or result['metrics']['average_precision'] > best['metrics']['average_precision']:
                best = result
                best_scores = scores.copy()
            print(f"Triage CV {len(trials)}/{len(configs)} AP={result['metrics']['average_precision']:.6f}", flush=True)
        vectorizer = DictVectorizer(sparse=False)
        features = vectorizer.fit_transform(records)
        estimator = _classifier(best['config'])
        estimator.fit(features, actual, sample_weight=np.where(actual, best['config']['positive_weight'], 1))
    metadata = {'name': 'Experimental final-risk triage classifier', 'status': 'experimental',
        'score_meaning': SCORE_MEANING, 'threshold': best['metrics']['threshold'],
        'threshold_rule': 'Maximum F2 on training-event out-of-fold scores; ties choose lower threshold.',
        'selection_rule': 'Highest three-fold training-event OOF average precision; no final labels used.',
        'hyperparameters': best['config'], 'max_iter': 100, 'learning_rate': .05, 'l2_regularization': 10,
        'cv': {'selected': best, 'trials': trials, 'external_training_only_search': search_trials,
               'baseline': triage_metrics(actual, latest, -6)},
        'seed': SEED, 'cutoff_days': 2., 'feature_count': len(vectorizer.feature_names_),
        'training_event_count': len(ids), 'high_risk_training_event_count': int(actual.sum()),
        'training_event_sha256': hashlib.sha256(','.join(map(str, ids)).encode()).hexdigest(),
        'training_data_sha256': digest(data / 'train_data.csv'),
        'sklearn_version': sklearn.__version__, 'numpy_version': np.__version__,
        'frozen_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'fit_elapsed_seconds': time.perf_counter() - started, 'final_test_labels_accessed': False,
        'limitations': ['Only 66 high-risk training events in the full eligible dataset.',
            'OOF metrics used for model and threshold selection are optimistic; final evaluation is retrospective.',
            'Class weighting and score calibration affect probabilities; scores are not calibrated.',
            'ESA selected encounters over-represent high-risk events; precision does not estimate operational prevalence.']}
    temporary = base / 'triage.joblib.partial'
    joblib.dump({'vectorizer': vectorizer, 'estimator': estimator, 'metadata': metadata}, temporary, compress=3)
    os.replace(temporary, base / 'triage.joblib')
    metadata['version'] = digest(base / 'triage.joblib')[:12]
    metadata['model_sha256'] = digest(base / 'triage.joblib')
    pd.DataFrame({'event_id': ids, 'high_risk_target': actual, 'latest_log10_pc': latest,
                  'triage_score': best_scores}).to_csv(base / 'triage_training_oof.csv', index=False)
    write_json(base / 'triage_metadata.json', metadata)
    return metadata


def evaluate_triage(root, bootstrap_repeats=1000):
    base, data = paths(root)
    if not (base / 'triage.joblib').exists() or not (base / 'triage_metadata.json').exists():
        raise ValueError('Freeze triage model and threshold before accessing final labels')
    metadata = json.loads((base / 'triage_metadata.json').read_text())
    before_hash = digest(base / 'triage.joblib')
    if before_hash != metadata['model_sha256']:
        raise ValueError('Frozen triage artifact hash mismatch')
    model = joblib.load(base / 'triage.joblib')
    ids, records, latest = feature_frame(pd.read_csv(data / 'test_data.csv'))
    scores = predict_triage(model, records)
    labels = read_labels(root).set_index('event_id')
    if set(ids) != set(labels.index):
        raise ValueError('Public input / released triage label event mismatch')
    target = labels.loc[ids, 'true_risk'].to_numpy(dtype=float)
    actual = target >= -6
    random = np.random.default_rng(SEED)
    differences = []
    for _ in range(bootstrap_repeats):
        indices = random.integers(0, len(ids), len(ids))
        if actual[indices].any():
            differences.append(float(average_precision_score(actual[indices], scores[indices]) -
                                     average_precision_score(actual[indices], latest[indices])))
    after_hash = digest(base / 'triage.joblib')
    if before_hash != after_hash:
        raise ValueError('Triage artifact changed during evaluation')
    evidence = {'status': 'experimental', 'source': 'ESA public retrospective final labels',
        'score_meaning': SCORE_MEANING, 'model': metadata,
        'metrics': triage_metrics(actual, scores, metadata['threshold']),
        'baseline': triage_metrics(actual, latest, -6),
        'paired_bootstrap': {'quantity': 'Triage minus raw latest average precision',
            'repeats': bootstrap_repeats, 'valid_repeats': len(differences),
            'ci95': np.quantile(differences, [.025, .975]).tolist() if differences else None},
        'validation': {'frozen_model_sha256_before_labels': before_hash,
            'model_sha256_after_evaluation': after_hash, 'event_sets_matched': True,
            'threshold_selected_on_training_only': True},
        'limitations': metadata['limitations']}
    pd.DataFrame({'event_id': ids, 'true_log10_pc': target, 'latest_log10_pc': latest,
                  'triage_score': scores, 'flagged': scores >= metadata['threshold']}).to_csv(
                      base / 'triage_test_predictions.csv', index=False)
    write_json(base / 'triage_evidence.json', evidence)
    return evidence
