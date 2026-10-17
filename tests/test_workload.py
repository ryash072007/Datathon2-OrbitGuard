import numpy as np
import pandas as pd
import pytest

from orbitguard.decision import workload as w


def test_threshold_matches_recall_on_train_only():
    y = np.array([1, 1, 1, 1, 0, 0, 0, 0], dtype=bool)
    s = np.array([.9, .8, .7, .3, .75, .2, .1, .05])
    t = w.match_recall_threshold(y, s, 0.75)
    assert t == .7
    assert ((s >= t) & y).sum() / y.sum() >= .75
    assert w.match_recall_threshold(y, s, 1.0) == .3


def test_labels_not_touched_before_thresholds_fixed():
    rng = np.random.default_rng(0)
    ytr = rng.random(200) < .3
    str_ = ytr * .5 + rng.random(200)
    ids = np.arange(100)
    state = {"frozen": False, "calls": 0}

    def reader():
        state["calls"] += 1
        return pd.Series(np.where(np.arange(100) < 30, -5.0, -8.0), index=ids)

    sc = np.where(np.arange(100) < 30, 1.5, .2)
    naive = np.arange(100) < 40
    res = w.run_workload({"m": (ytr, str_)}, {"m": sc}, ids, naive, {"act": naive}, 0.9, reader, repeats=50)
    assert state["calls"] == 1
    assert res["thresholds"]["m"]["train_oof_recall"] >= .9
    assert res["policies"][w.NAIVE]["caught"] == 30 and res["policies"][w.NAIVE]["false_alerts"] == 10
    assert res["policies"]["matched:m"]["false_alerts"] == 0
    assert isinstance(res["summary"], str) and "Best safety-first" in res["summary"]
    assert res["paired_bootstrap_vs_naive"]["matched:m"]["false_alerts_difference"]["point"] == -10


def test_reader_failure_propagates_not_swallowed():
    def reader():
        raise ValueError("Freeze decision.joblib before opening final test labels")

    with pytest.raises(ValueError, match="Freeze"):
        w.run_workload({"m": (np.array([True, False]), np.array([.9, .1]))}, {"m": np.array([.9, .1])},
                       np.array([0, 1]), np.array([True, False]), {}, 1.0, reader, repeats=5)


def test_bootstrap_ci_shape_and_sign():
    high = np.r_[np.ones(30, bool), np.zeros(70, bool)]
    naive = np.ones(100, bool)
    better = high.copy()
    b = w.paired_bootstrap({"n": naive, "b": better}, high, "n", repeats=200)
    d = b["b"]["false_alerts_removed"]
    assert len(d["ci95"]) == 2 and d["ci95"][0] <= d["point"] <= d["ci95"][1]
    assert d["point"] == 70 and d["ci95"][0] > 0
    assert b["b"]["recall_difference"]["point"] == 0


def test_missing_optional_snapml_is_skipped(tmp_path):
    assert w._optional_snapml(tmp_path, np.array([1]), pd.Series([True], index=[1]), np.array([1])) is None


def test_run_requires_frozen_artefacts(tmp_path):
    with pytest.raises(FileNotFoundError):
        w.run(tmp_path, repeats=5)


def test_budget_rows_use_naive_alert_count_and_rank_summary():
    ids = np.arange(100)
    ytr = np.arange(100) < 30
    str_ = ytr * 1.0
    naive = (np.arange(100) % 3) == 0  # 34 alerts, catches 10 of the 30 highs
    sc = np.where(np.arange(100) < 30, 1.0, 0.0) - np.arange(100) * 1e-4

    def reader():
        return pd.Series(np.where(np.arange(100) < 30, -5.0, -8.0), index=ids)

    res = w.run_workload({"m": (ytr, str_)}, {"m": sc}, ids, naive, {}, 0.9, reader, repeats=50,
                         naive_score=naive.astype(float))
    assert res["alert_budget_k"] == 34
    assert res["policies"]["budget:m"]["alerts"] == 34
    assert res["policies"]["budget:m"]["caught"] == 30
    cd = res["paired_bootstrap_vs_naive"]["budget:m"]["caught_difference"]
    assert cd["point"] == 30 - res["policies"][w.NAIVE]["caught"] and len(cd["ci95"]) == 2
    assert res["ranking_caught_at_budget"]["m"]["34"] == 30
    assert set(res["ranking_caught_at_budget"]) == {"naive_latest_risk", "m"}


def test_extra_reviews_and_plain_budget_statement():
    ids = np.arange(100)
    ytr = np.arange(100) < 30
    naive = (np.arange(100) % 3) == 0
    sc = (np.arange(100) % 3 == 0) * 1.0 + (np.arange(100) < 30) * 0.1

    def reader():
        return pd.Series(np.where(np.arange(100) < 30, -5.0, -8.0), index=ids)

    res = w.run_workload({"m": (ytr, sc * 0 + ytr)}, {"m": sc}, ids, naive, {"act": naive}, 0.9, reader, repeats=30)
    b = res["paired_bootstrap_vs_naive"]
    assert b["act"]["extra_reviews_per_extra_caught"] is None
    assert b["matched:m"]["extra_reviews_per_extra_caught"] is None or b["matched:m"]["extra_reviews_per_extra_caught"] >= 0
    assert len(b["budget:m"]["false_alerts_difference"]["ci95"]) == 2
    assert "equal budget" in res["summary"]
