"""Guard evaluation harness with a fake Guardian (no model)."""
from __future__ import annotations

import json

from orbitguard.brief import guard_eval, guardian


def test_wilson_interval():
    lo, hi = guard_eval.wilson(8, 10)
    assert 0.49 < lo < 0.50 and 0.94 < hi < 0.95
    assert guard_eval.wilson(0, 0) is None and guard_eval.wilson(10, 10)[1] == 1.0


def test_numeric_only_without_guardian(monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    rep = guard_eval.evaluate(10, 1)
    assert "guardian" not in rep["results"] and rep["guardian"]["configured"] is False
    assert "Guardian not configured" in rep["summary"]
    r = rep["results"]["numeric_guard"]
    assert r["false_flag_on_good"]["k"] == 0 and r["numeric"]["rate"] >= 0.8
    assert r["non_numeric"]["k"] == 0  # the numeric guard is blind to contradictions without new numbers


def test_fake_guardian_combined(monkeypatch):
    monkeypatch.setenv(guardian.ENV_PATH, "/m/granite-guardian-3.2-3b-a800m-Q8_0.gguf")
    bad_words = ("safe", "No burn is needed", "ENVISAT", "STARSHIP", "LANDSAT", "GLONASS", "Execute")
    fake = lambda ctx, text: {"status": "ok", "flagged": any(w in text for w in bad_words), "latency_ms": 5.0}
    rep = guard_eval.evaluate(10, 2, check=fake)
    g = rep["results"]["guardian"]
    assert rep["guardian"]["quant"] == "Q8_0" and rep["guardian"]["latency_ms"]["mean"] == 5.0
    assert g["false_flag_on_good"]["k"] == 0 and g["non_numeric"]["rate"] >= 0.6
    assert rep["results"]["combined"]["numeric"]["rate"] >= rep["results"]["numeric_guard"]["numeric"]["rate"]
    assert rep["results"]["combined"]["non_numeric"]["k"] >= g["non_numeric"]["k"] - 0


def test_cli_writes_json(tmp_path, monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    out = tmp_path / "ge.json"
    assert guard_eval.main(["--n", "5", "--seed", "3", "--out", str(out)]) == 0
    d = json.loads(out.read_text())
    assert d["n_per_class"] == 5 and d["platform"]["machine"] and "Q4_K_M" in " ".join(d["notes"])
