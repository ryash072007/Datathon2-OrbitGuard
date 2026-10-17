import numpy as np
import pandas as pd
import pytest

from orbitguard.ml.triage import choose_threshold, evaluate_triage, predict_triage, triage_metrics


def test_threshold_is_frozen_from_training_f2_and_respects_ties():
    actual = np.array([True, True, False, False])
    scores = np.array([.9, .2, .2, .1])
    threshold = choose_threshold(actual, scores)
    assert threshold == .2
    metrics = triage_metrics(actual, scores, threshold)
    assert metrics['recall'] == 1
    assert metrics['precision'] == pytest.approx(2 / 3)
    assert metrics['f2'] == pytest.approx(10 / 11)


def test_ranking_metrics_use_unclipped_scores():
    result = triage_metrics([True, False, False, True], [.9, .8, .2, .1], .5)
    assert result['average_precision'] == .75
    assert result['top_10_percent_recall'] == .5
    assert [result[key] for key in ('tp', 'fp', 'fn', 'tn')] == [1, 1, 1, 1]


def test_triage_predictions_are_bounded_and_preserve_order():
    from sklearn.dummy import DummyClassifier
    from sklearn.feature_extraction import DictVectorizer
    vectorizer = DictVectorizer(sparse=False)
    features = vectorizer.fit_transform([{'risk': -5}, {'risk': -8}])
    estimator = DummyClassifier(strategy='prior').fit(features, [True, False])
    result = predict_triage({'vectorizer': vectorizer, 'estimator': estimator}, [{'risk': -7}])
    np.testing.assert_array_equal(result, [.5])


def test_final_labels_require_frozen_triage_artifact(tmp_path):
    with pytest.raises(ValueError, match='Freeze'):
        evaluate_triage(tmp_path)


def test_training_freezes_model_without_opening_final_labels(tmp_path, monkeypatch):
    import json
    import joblib
    from orbitguard.ml import triage
    from orbitguard.ml.data import digest
    messages = []
    for event_id in range(30):
        high_risk = event_id % 4 == 0
        for time_to_tca in [4., 2., .1]:
            messages.append({'event_id': event_id, 'time_to_tca': time_to_tca,
                             'risk': -5. if high_risk else -9.})
    data = tmp_path / 'artifacts/ml/data'
    data.mkdir(parents=True)
    pd.DataFrame(messages).to_csv(data / 'train_data.csv', index=False)
    def forbid_labels(root):
        raise AssertionError('Final labels must not be opened during training')
    monkeypatch.setattr(triage, 'read_labels', forbid_labels)
    metadata = triage.train_triage(tmp_path, configs=[{
        'max_leaf_nodes': 7, 'min_samples_leaf': 2, 'positive_weight': 1}])
    base = data.parent
    assert metadata['final_test_labels_accessed'] is False
    assert metadata['model_sha256'] == digest(base / 'triage.joblib')
    assert json.loads((base / 'triage_metadata.json').read_text())['threshold'] == metadata['threshold']
    oof = pd.read_csv(base / 'triage_training_oof.csv')
    assert len(oof) == 30 and oof.event_id.is_unique
    assert oof.triage_score.between(0, 1).all()
    model = joblib.load(base / 'triage.joblib')
    assert predict_triage(model, [{'latest_risk': -5., 'latest_time_to_tca': 2.}])[0] > .5
    pd.DataFrame([
        {'event_id': 100, 'time_to_tca': 2., 'risk': -5.},
        {'event_id': 101, 'time_to_tca': 2., 'risk': -9.},
    ]).to_csv(data / 'test_data.csv', index=False)
    monkeypatch.setattr(triage, 'read_labels', lambda root: pd.DataFrame({
        'event_id': [101, 100], 'true_risk': [-9., -5.]}))
    evidence = evaluate_triage(tmp_path, bootstrap_repeats=20)
    assert evidence['metrics']['average_precision'] == 1
    assert evidence['metrics']['threshold'] == metadata['threshold']
    assert evidence['validation']['frozen_model_sha256_before_labels'] == metadata['model_sha256']
    assert evidence['validation']['model_sha256_after_evaluation'] == metadata['model_sha256']
    assert (base / 'triage_test_predictions.csv').exists()
    assert (base / 'triage_evidence.json').exists()
