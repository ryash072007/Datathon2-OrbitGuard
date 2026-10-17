import pandas as pd
import pytest

from orbitguard.api import create_app
from orbitguard.ml.service import MLService


@pytest.fixture
def replay(tmp_path):
    service = MLService(tmp_path)
    service._events = pd.DataFrame([
        {'event_id': '7', 'time_to_tca': 2., 'risk': -5.},
        {'event_id': '7', 'time_to_tca': 4., 'risk': -8.},
        {'event_id': '7', 'time_to_tca': 3., 'risk': -7.},
    ])
    calls = []

    def forecast(history):
        calls.append(history)
        return {'forecast_log10_pc': history[-1]['risk'], 'model_version': 'test'}

    service.forecast = forecast
    return service, calls


def test_replay_uses_only_available_prefix_and_reports_transition(replay):
    service, calls = replay
    update = service.replay_update('7', 2)
    assert [row['time_to_tca'] for row in calls[0]] == [4., 3.]
    assert all(row['risk'] != -5 for history in calls for row in history)
    assert update['alert']['state'] == 'monitor'
    assert update['source'] == 'historical_replay'
    assert 'reference' not in update
    assert update['processing_ms'] >= 0
    assert update['completed_at'] >= update['received_at']
    high = service.replay_update('7', 3)
    assert high['alert'] == {'state': 'high_risk', 'previous_state': 'monitor', 'changed': True}
    assert high['action'] == 'Operator review required; no automatic manoeuvre.'


def test_replay_is_stateless_for_duplicates_and_out_of_order_requests(replay):
    service, _ = replay
    first = service.replay_update('7', 3)
    service.replay_update('7', 1)
    repeated = service.replay_update('7', 3)
    assert repeated['update_id'] == first['update_id']
    assert repeated['alert'] == first['alert']
    assert service.replay_update('7', 1)['alert']['previous_state'] is None


@pytest.mark.parametrize('count', [0, -1, 4, True, '2', 1.5, None])
def test_invalid_replay_position(replay, count):
    service, calls = replay
    with pytest.raises(ValueError):
        service.replay_update('7', count)
    assert calls == []


def test_replay_failure_does_not_publish_success(replay):
    service, _ = replay

    def fail(history):
        raise FileNotFoundError('Model unavailable')

    service.forecast = fail
    with pytest.raises(FileNotFoundError):
        service.replay_update('7', 1)


def test_replay_api_validation_and_processing(replay, tmp_path):
    service, _ = replay
    client = create_app(tmp_path, ml_service=service).test_client()
    result = client.post('/api/replay/update', json={'event_id': '7', 'message_count': 3})
    assert result.status_code == 200
    assert result.json['alert']['state'] == 'high_risk'
    for identity in [None, [], '', 7]:
        assert client.post('/api/replay/update', json={'event_id': identity, 'message_count': 1}).status_code == 422
    assert client.post('/api/replay/update', json={'event_id': 'missing', 'message_count': 1}).status_code == 404
    assert client.post('/api/replay/update', json={'event_id': '7', 'message_count': 4}).status_code == 422


def test_experimental_review_is_not_a_default_high_risk_prediction(replay):
    service, _ = replay
    service.forecast = lambda history: {'forecast_log10_pc': -8., 'supplemental_review': {'additional_review': True}}
    assert service.replay_update('7', 1)['alert']['state'] == 'additional_review'


def test_replay_api_failure_can_be_retried(replay, tmp_path):
    service, _ = replay
    client = create_app(tmp_path, ml_service=service).test_client()
    forecast = service.forecast

    def fail(history):
        raise FileNotFoundError('Unavailable')

    service.forecast = fail
    failed = client.post('/api/replay/update', json={'event_id': '7', 'message_count': 1})
    assert failed.status_code == 503
    assert 'alert' not in failed.json
    service.forecast = forecast
    assert client.post('/api/replay/update', json={'event_id': '7', 'message_count': 1}).json['alert']['state'] == 'monitor'
