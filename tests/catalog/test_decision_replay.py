"""Decision replay: monotonic time, valid actions, honest ground truth (real model if available)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from orbitguard.decision import replay as R


def _cdms(n=6):
    t = np.linspace(5.0, 0.3, n)
    return pd.DataFrame({"event_id": 1, "time_to_tca": t, "risk": np.linspace(-8, -5, n)})


def test_replay_with_stub_decision(monkeypatch):
    seen = []

    def fake(u, art=None):
        seen.append(len(u))
        assert (u["time_to_tca"] >= 2).all()
        act = "ACT" if len(u) > 2 else "MONITOR"
        return R.Decision(float(u["risk"].iloc[-1]), -6.0, 0.1 * len(u), (-7.0, -5.0), act, ["r"])

    monkeypatch.setattr(R, "decide", fake)
    steps = R.replay_cdms(_cdms(), -5.2, art={})
    body = [s for s in steps if not s.get("final")]
    t = [s["time_to_tca_days"] for s in body]
    assert t == sorted(t, reverse=True) and min(t) >= 2.0
    assert seen == list(range(1, len(body) + 1))
    assert {s["action"] for s in body} <= set(R.ACTIONS)
    assert steps[-1]["final"] and steps[-1]["true_high"] is True


def test_replay_empty_raises():
    with pytest.raises(ValueError):
        R.replay_cdms(_cdms().assign(time_to_tca=1.0), None, art={})


@pytest.mark.skipif(not (R.DATA / "test_data.csv").exists() or not (R.DATA.parents[2] / "models" / "decision.joblib").exists(),
                    reason="ESA data or decision model not available")
def test_replay_real_event():
    steps = R.replay(276)
    body = [s for s in steps if not s.get("final")]
    t = [s["time_to_tca_days"] for s in body]
    assert t == sorted(t, reverse=True) and min(t) >= 2.0
    assert {s["action"] for s in body} <= set(R.ACTIONS)
    assert steps[-1]["final"] and "true_final_risk" in steps[-1]
