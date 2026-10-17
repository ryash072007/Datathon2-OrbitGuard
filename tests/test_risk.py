import numpy as np
import pandas as pd
import pytest

from src.risk.features import build_table, event_features
from src.risk.train import DATA, MODEL_PATH


def _cdms(ttca, risk):
    n = len(ttca)
    return pd.DataFrame({
        "event_id": [1] * n, "time_to_tca": ttca, "risk": risk, "mission_id": [3] * n,
        "c_object_type": ["DEBRIS"] * n, "miss_distance": np.linspace(1000, 500, n),
        "relative_speed": [7000.0] * n,
    })


def test_single_cdm():
    f = event_features(_cdms([5.0], [-7.0]))
    assert f["n_cdms"] == 1 and f["risk_slope"] == 0 and f["naive_risk"] == -7.0
    assert f["c_object_type"] == "DEBRIS"


def test_several_cdms_ignores_late():
    f = event_features(_cdms([6.0, 4.0, 2.5, 0.5], [-8.0, -7.0, -6.0, -2.0]))
    assert f["n_cdms"] == 3 and f["naive_risk"] == -6.0 and f["risk_first"] == -8.0
    assert f["risk_delta_last2"] == pytest.approx(1.0)
    assert f["risk_slope"] < 0  # risk rises as time_to_tca falls
    assert f["time_span_days"] == pytest.approx(3.5)


def test_no_usable():
    with pytest.raises(ValueError):
        event_features(_cdms([1.5, 0.2], [-5.0, -4.0]))


def test_build_table_labels():
    df = pd.concat([_cdms([5.0, 3.0], [-7, -6]), _cdms([4.0], [-9]).assign(event_id=2)])
    t = build_table(df, pd.Series({1: -5.0}))
    assert list(t.index) == [1] and t.loc[1, "target"] == -5.0


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="model not trained")
def test_predict_end_to_end():
    from src.risk.predict import predict_risk
    df = pd.read_csv(DATA / "test_data.csv", nrows=200)
    eid = df["event_id"].iloc[0]
    assert -30 <= predict_risk(df[df.event_id == eid]) <= 0
