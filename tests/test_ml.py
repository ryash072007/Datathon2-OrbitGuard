import numpy as np
import pandas as pd
import pytest
from orbitguard.ml.data import read_labels
from orbitguard.ml.model import _xy,clipped,feature_frame,metrics
from orbitguard.ml.service import MLService

def rows():
    return pd.DataFrame([
        {'event_id':7,'mission_id':99,'time_to_tca':4.,'risk':-8.,'miss_distance':400.,'t_sigma_r':2.},
        {'event_id':7,'mission_id':99,'time_to_tca':2.,'risk':-7.,'miss_distance':300.,'t_sigma_r':np.nan},
        {'event_id':7,'mission_id':99,'time_to_tca':.1,'risk':-5.,'miss_distance':2.,'t_sigma_r':50.},
        {'event_id':8,'mission_id':88,'time_to_tca':4.,'risk':-9.,'miss_distance':500.,'t_sigma_r':4.},
        {'event_id':8,'mission_id':88,'time_to_tca':1.5,'risk':-8.,'miss_distance':450.,'t_sigma_r':7.},
    ])

def test_future_messages_cannot_enter_features():
    with pytest.raises(ValueError,match='at least 2'): feature_frame(rows())
    ids,features,latest,y=_xy(rows())
    assert ids.tolist()==[7] # event 8 has no final-day reference
    assert latest.tolist()==[-7.]
    assert y.tolist()==[-5.]
    assert features[0]['latest_miss_distance']==300
    assert features[0]['history_message_count']==2
    assert features[0]['history_risk_change']==1
    assert not any('mission_id' in k or 'event_id' in k for k in features[0])
    # Missing latest values must not silently backfill from an older message.
    assert 'latest_t_sigma_r' not in features[0]

def test_feature_permutation_does_not_change_history():
    valid=rows().query('time_to_tca >= 2')
    a=feature_frame(valid); b=feature_frame(valid.sample(frac=1,random_state=9))
    assert a[0].tolist()==b[0].tolist(); assert a[1]==b[1]; np.testing.assert_array_equal(a[2],b[2])

def test_score_uses_high_risk_mse_and_f2():
    result=metrics(np.array([-5.,-4.,-8.,-9.]),np.array([-5.,-7.,-5.,-8.]))
    assert [result[k] for k in ('tp','fp','fn','tn')]==[1,1,1,1]
    assert result['f2']==.5
    assert result['challenge_loss']==9. # high-risk MSE=(0+9)/2; divide by .5
    assert metrics([-5.],[-8.])['challenge_loss'] is None

def test_scoring_clip_never_changes_high_risk_predictions():
    np.testing.assert_allclose(clipped([-20.,-6.01,-6.,-2.]),[-6.001,-6.001,-6.,-2.])


def test_zero_learned_residual_preserves_raw_low_probability_information():
    from sklearn.dummy import DummyRegressor
    from sklearn.feature_extraction import DictVectorizer
    from orbitguard.ml.model import predict
    records = [{'latest_risk': -12.}, {'latest_risk': -5.}]
    vectorizer = DictVectorizer(sparse=False)
    features = vectorizer.fit_transform(records)
    estimator = DummyRegressor(strategy='constant', constant=0).fit(features, [0., 0.])
    model = {'vectorizer': vectorizer, 'estimator': estimator,
             'metadata': {'selected_method': 'latest_baseline', 'learned_alpha': 1.}}
    np.testing.assert_allclose(predict(model, records, [-30., -5.], learned=True), [-30., -5.])

def test_private_labels_require_frozen_artifact(tmp_path):
    with pytest.raises(ValueError,match='Freeze'): read_labels(tmp_path)

def test_inference_rejects_mixed_events_labels_and_sparse_failures(tmp_path):
    service=MLService(tmp_path)
    with pytest.raises(ValueError,match='exactly one'): service.forecast([{'event_id':1,'risk':-5,'time_to_tca':3},{'event_id':2,'risk':-6,'time_to_tca':4}])
    with pytest.raises(ValueError,match='Evaluation labels'): service.forecast([{'event_id':1,'risk':-5,'time_to_tca':3,'true_risk':-4}])
    with pytest.raises(ValueError,match='at least 2'): service.forecast([{'event_id':1,'risk':-5,'time_to_tca':1.9}])
    with pytest.raises(ValueError,match='at most zero'): service.forecast([{'event_id':1,'risk':.1,'time_to_tca':3}])
    with pytest.raises(ValueError,match='finite numeric'): service.forecast([{'event_id':1,'risk':float('nan'),'time_to_tca':3}])
    assert service.evidence()['status']=='missing'


def test_target_at_exactly_one_day_is_excluded():
    frame=rows()
    frame.loc[(frame.event_id==7)&(frame.time_to_tca==.1),'time_to_tca']=1.
    ids,features,latest,y=_xy(frame)
    assert len(ids)==0


def test_evidence_does_not_publish_metrics_for_a_different_frozen_model(tmp_path):
    import json
    base = tmp_path / 'artifacts/ml'
    base.mkdir(parents=True)
    (base / 'model.joblib').write_bytes(b'new frozen model')
    (base / 'evidence.json').write_text(json.dumps({
        'status': 'ready', 'metrics': [{'challenge_loss': .1}],
        'validation': {'model_sha256_after_evaluation': 'old model hash'},
    }))
    result = MLService(tmp_path).evidence()
    assert result['status'] == 'stale'
    assert 'metrics' not in result


def test_population_and_ranking_curves_from_artifacts(tmp_path):
    import pandas as pd
    from orbitguard.ml.service import MLService
    data = tmp_path / "artifacts/ml/data"
    data.mkdir(parents=True)
    pd.DataFrame({"event_id": [1, 1, 2], "time_to_tca": [3.0, 2.1, 2.5], "risk": [-7.0, -5.0, -9.0],
                  "c_object_type": ["DEBRIS", "DEBRIS", None], "c_j2k_inc": [98.0, 98.1, 74.0]}).to_csv(data / "test_data.csv", index=False)
    pd.DataFrame({"event_id": ["1", "2"], "true_log10_pc": [-5.5, -9.0], "latest_log10_pc": [-5.0, -9.0],
                  "forecast_log10_pc": [-5.0, -9.0], "learned_log10_pc": [-6.0, -8.0]}).to_csv(tmp_path / "artifacts/ml/test_predictions.csv", index=False)
    service = MLService(tmp_path)
    overview = service.overview()
    assert overview["count"] == 2
    # Only the latest message per event is summarised, and missing types are labelled explicitly.
    assert dict(zip(overview["columns"]["event_id"], overview["columns"]["risk"]))["1"] == -5.0
    assert "UNKNOWN" in overview["columns"]["c_object_type"]
    curves = service.ranking_curves()
    assert set(curves) == {"latest", "learned"} and all(0 <= p["precision"] <= 1 for p in curves["latest"])
