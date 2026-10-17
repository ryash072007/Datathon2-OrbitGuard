import numpy as np
import pytest

from orbitguard.ml.accuracy import fit_shrinkage, shrink_risk, classification_intervals, audit_metrics


def test_shrinkage_preserves_alert_decisions_and_raw_low_risks():
    risks = np.array([-30., -8., -6.001, -6., -5., -2., 0.])
    adjusted = shrink_risk(risks, .5)
    np.testing.assert_array_equal(adjusted >= -6, risks >= -6)
    np.testing.assert_array_equal(adjusted[:3], risks[:3])
    np.testing.assert_allclose(adjusted[3:], [-6., -5.5, -4., -3.])


def test_shrinkage_is_fitted_only_to_supplied_training_targets():
    assert fit_shrinkage([-5., -4., -9.], [-5.5, -5., -8.]) == pytest.approx(.5)
    assert fit_shrinkage([-9., -8.], [-8., -9.]) == 1.
    assert fit_shrinkage([-5.], [-4.]) == 1.
    assert 0 < fit_shrinkage([-4.], [-6.]) <= 1


def test_confidence_bounds_keep_small_samples_and_zero_misses_visible():
    intervals = classification_intervals([True, True, False], [True, True, False])
    assert intervals['recall_ci95'][0] < 1
    assert intervals['recall_ci95'][1] == pytest.approx(1)
    assert intervals['precision_ci95'][0] < 1
    assert classification_intervals([False], [False])['recall_ci95'] is None


def test_audit_metrics_report_raw_errors_and_dumb_baseline():
    result = audit_metrics([-5., -4., -8., -9.], [-5., -7., -5., -8.])
    assert result['log10_mae'] == pytest.approx(1.75)
    assert result['always_low_risk_accuracy'] == .5
    assert result['confusion_matrix'] == {'true_positive': 1, 'false_positive': 1, 'false_negative': 1, 'true_negative': 1}
    assert result['classification_accuracy'] == .5
