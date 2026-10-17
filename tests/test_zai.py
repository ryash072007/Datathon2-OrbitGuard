"""Snap ML second opinion: fit/import roundtrip, label freeze, service attachment. Tiny synthetic fixtures."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from orbitguard.decision.features import build_table
from orbitguard.zai import snap


def _cdms(n_events=240, seed=0):
    rng = np.random.default_rng(seed)
    rows, final = [], {}
    for e in range(n_events):
        base = rng.uniform(-9, -4)
        for t in (5.0, 4.0, 3.0, 2.2):
            rows.append({"event_id": e, "time_to_tca": t, "risk": base + rng.normal(0, 0.2),
                         "miss_distance": rng.uniform(10, 5000), "max_risk_estimate": base + 0.1,
                         "mahalanobis_distance": rng.uniform(1, 100), "c_object_type": "DEBRIS"})
        final[e] = base + rng.normal(0, 0.3)
    return pd.DataFrame(rows), pd.Series(final)


@pytest.fixture(scope="module")
def tab():
    pytest.importorskip("snapml")
    cdms, final = _cdms()
    return build_table(cdms, final)


@pytest.fixture()
def fitted(tab, tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "GRID", snap.GRID[:1])
    meta = snap.cmd_fit(tmp_path / "artifacts" / "zai", tab=tab)
    return tmp_path, meta


def test_fit_import_roundtrip(fitted, tab):
    root, meta = fitted
    pmml = root / "artifacts" / "zai" / "snapml_bmc.pmml"
    assert meta["model_sha256"] == snap.sha256_file(pmml)
    assert meta["roundtrip_max_abs_diff_native_vs_imported_cpu"] < 1e-4
    p = snap.load_scorer(pmml, "compress_trees").predict_proba(snap.featurize(tab, meta["train_medians"]))
    assert p.shape == (len(tab),) and ((0 <= p) & (p <= 1)).all()


def test_zdnn_import_is_reported_not_fatal(fitted):
    root, _ = fitted
    pmml = root / "artifacts" / "zai" / "snapml_bmc.pmml"
    if snap.nnpa_in_cpuinfo():
        assert snap.load_scorer(pmml, "zdnn_tensors").backend == "snapml-zdnn"
    else:
        with pytest.raises(RuntimeError):
            snap.load_scorer(pmml, "zdnn_tensors")


def test_eval_refuses_before_freeze(tmp_path):
    with pytest.raises(ValueError, match="Freeze"):
        snap.cmd_eval(tmp_path / "missing.pmml", tmp_path / "evidence.json")
    assert not (tmp_path / "evidence.json").exists()


def test_bootstrap_ci_reports_undefined_without_positives():
    out = snap.paired_bootstrap_ap_diff(np.zeros(20, dtype=int), np.arange(20.0), np.arange(20.0)[::-1], n=10)
    assert out["status"] == "undefined"


def test_service_attaches_second_opinion_without_changing_action(fitted):
    from orbitguard.ml.service import MLService
    root, meta = fitted
    cdms, _ = _cdms(1, seed=3)
    svc = MLService(root)
    for p_main in (0.01, 0.99):
        decision = {"status": "ready", "action": "WAIT", "p_high": p_main, "reasons": ["x"]}
        out = svc._attach_second_opinion(dict(decision, reasons=["x"]), cdms)
        so = out["second_opinion"]
        assert out["action"] == "WAIT"
        assert so["backend"] in ("snapml-cpu", "snapml-zdnn") and 0 <= so["p_high"] <= 1 and so["latency_ms"] >= 0
        assert so["agrees"] == (((so["p_high"] >= 0.5) == (p_main >= 0.5)) or abs(so["p_high"] - p_main) < 0.25)
        assert (len(out["reasons"]) == 2) == (not so["agrees"])


def test_service_without_artefact_adds_nothing(tmp_path):
    from orbitguard.ml.service import MLService
    cdms, _ = _cdms(1)
    d = {"status": "ready", "action": "ACT", "p_high": 0.9, "reasons": []}
    assert "second_opinion" not in MLService(tmp_path)._attach_second_opinion(d, cdms)
