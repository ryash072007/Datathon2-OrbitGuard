import numpy as np
import pytest

from orbitguard.ml.guard import choose_guard, guard_predictions, evaluate_guard


def test_guard_adds_missed_alerts_without_suppressing_baseline_or_exceeding_budget():
    actual = np.array([True, True, True, False, False, False, False])
    latest = np.array([-5., -7., -8., -5., -8., -8., -8.])
    learned = np.array([-8., -5., -4., -4., -5.5, -8., -9.])
    policy = choose_guard(actual, latest, learned)
    assert policy['threshold'] == -5.
    assert policy['metrics']['tp'] == 3
    assert policy['metrics']['fp'] == 1
    assert policy['false_positive_budget'] == 1


def test_guard_preserves_risk_forecasts_except_explicit_escalations():
    latest = np.array([-4., -7., -20., -6.])
    learned = np.array([-9., -5., -9., -10.])
    policy = {'threshold': -5.5, 'escalated_log10_pc': -5.4}
    actual = guard_predictions(latest, learned, policy)
    np.testing.assert_allclose(actual, [-4., -5.4, -20., -6.])
    assert np.all(actual[latest >= -6] == latest[latest >= -6])
    np.testing.assert_array_equal(guard_predictions(latest, learned, {**policy, 'threshold': None}), latest)


def test_guard_does_not_split_tied_scores_to_invent_a_feasible_policy():
    policy = choose_guard([True, True, False], [-5., -8., -8.], [-9., -4., -4.])
    assert policy['threshold'] is None
    assert policy['metrics']['fn'] == 1


def test_guard_rejects_invalid_forecasts_and_unfrozen_evaluation(tmp_path):
    with pytest.raises(ValueError, match='finite'):
        guard_predictions([-8.], [float('nan')], {'threshold': -5., 'escalated_log10_pc': -5.4})
    with pytest.raises(ValueError, match='Freeze'):
        evaluate_guard(tmp_path)


def test_live_supplemental_review_requires_matching_frozen_artifacts(tmp_path):
    from pathlib import Path
    import json
    from orbitguard.ml import guard, model
    from orbitguard.ml.data import digest
    from orbitguard.ml.service import MLService
    service = MLService(tmp_path)
    assert service._supplemental_review(-7., -5.) is None
    base = tmp_path / 'artifacts/ml'
    base.mkdir(parents=True)
    model_path = base / 'model.joblib'
    model_path.write_bytes(b'frozen base')
    policy = {'threshold': -5.5, 'escalated_log10_pc': -5.4,
              'baseline_model_sha256': digest(model_path),
              'guard_source_sha256': digest(Path(guard.__file__)),
              'prediction_source_sha256': digest(Path(model.__file__))}
    (base / 'guard_policy.json').write_text(json.dumps(policy))
    result = service._supplemental_review(-7., -5.)
    assert result['additional_review'] is True
    assert result['candidate_log10_pc'] == -5.4
    assert service._supplemental_review(-5., -5.)['additional_review'] is False
    model_path.write_bytes(b'a different frozen base')
    stale = service._supplemental_review(-7., -5.)
    assert stale['status'] == 'stale'
    assert 'additional_review' not in stale


def test_guard_training_is_event_nested_and_never_opens_test_labels(tmp_path, monkeypatch):
    import json
    import pandas as pd
    from orbitguard.ml import guard
    from orbitguard.ml.data import digest
    base = tmp_path / 'artifacts/ml'
    data = base / 'data'
    data.mkdir(parents=True)
    messages = []
    for event_id in range(60):
        for time_to_tca in [3., 2., .1]:
            messages.append({'event_id': event_id, 'time_to_tca': time_to_tca, 'risk': -5. if event_id % 4 == 0 else -9.})
    pd.DataFrame(messages).to_csv(data / 'train_data.csv', index=False)
    (base / 'model.joblib').write_bytes(b'base fingerprint for isolated training test')
    (base / 'model_metadata.json').write_text(json.dumps({'learned_alpha': .5,
        'hyperparameters': {'max_leaf_nodes': 7, 'min_samples_leaf': 2, 'l2_regularization': 1, 'high_risk_weight': 10}}))
    def forbidden(root):
        raise AssertionError('Final labels cannot be accessed while fitting the guard')
    monkeypatch.setattr(guard, 'read_labels', forbidden)
    policy = guard.train_guard(tmp_path)
    assert policy['final_test_labels_accessed'] is False
    assert policy['default_changed'] is False
    assert policy['baseline_model_sha256'] == digest(base / 'model.joblib')
    assert len(policy['nested_validation']['folds']) == 3
    assert sum(fold['validation_events'] for fold in policy['nested_validation']['folds']) == 60
    assert policy['nested_validation']['guard']['fn'] == 0
    assert json.loads((base / 'guard_policy.json').read_text())['threshold'] is None
