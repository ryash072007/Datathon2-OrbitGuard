"""Guard evaluation harness, numeric-guard gaps and the claim checker (fakes only, no model)."""
from __future__ import annotations

import json
import random

import pytest

from orbitguard.brief import guard_eval, guardian
from orbitguard.brief.claims import check_claims
from orbitguard.brief.grounding import check_grounding
from orbitguard.brief.template import render_template


def test_wilson_interval():
    lo, hi = guard_eval.wilson(8, 10)
    assert 0.49 < lo < 0.50 and 0.94 < hi < 0.95
    assert guard_eval.wilson(0, 0) is None and guard_eval.wilson(10, 10)[1] == 1.0


def test_numeric_guard_rejects_coarse_scaled_coincidences(facts):
    # "0.0" and "0.1" used to be grounded by a unit-scaled copy of almost any fact; low precision cannot claim that
    assert check_grounding("The miss is 0.1 km.", {"a": 33.7}) == ["0.1"]
    assert check_grounding("The miss is 4.98 km.", {"a": 4980.0}) == []  # genuine unit change still passes
    assert check_grounding(render_template(facts), facts) == []  # the 0.5x-2x sweep constants are not facts


def test_claims_pass_good_and_catch_categorical_contradictions():
    rng = random.Random(5)
    for _ in range(20):
        f = guard_eval.make_facts(rng)
        good = render_template(f)
        assert check_claims(good, f) == []
        for kind in guard_eval.NONNUMERIC:
            bad = guard_eval.corrupt_nonnumeric(kind, good, f, rng)
            assert bad and check_claims(bad, f), kind


def test_claims_are_silent_without_anchor():
    f = guard_eval.make_facts(random.Random(1))
    assert check_claims("The situation is being monitored by the team.", f) == []
    assert check_claims("It is guaranteed to be fine.", f)  # overconfident phrase needs no anchor


def test_numeric_only_without_guardian(monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    rep = guard_eval.evaluate(10, 1)
    assert rep["guardian"]["configured"] is False and "Guardian not configured" in rep["summary"]
    r = rep["results"]
    assert r["false_flags_synthetic_good"]["numeric+claims"]["k"] == 0
    assert r["synthetic_non_numeric"]["claims"]["rate"] >= 0.9 and r["synthetic_non_numeric"]["numeric"]["k"] <= 1
    assert r["synthetic_numeric"]["numeric+claims"]["rate"] >= 0.7


def test_fake_guardian_rows_and_heldout(monkeypatch):
    monkeypatch.setenv(guardian.ENV_PATH, "/m/granite-guardian-3.2-3b-a800m-Q8_0.gguf")
    fake = lambda ctx, text, mode: {"status": "ok", "flagged": "guaranteed" in text, "latency_ms": 5.0}
    f = guard_eval.make_facts(random.Random(9))
    good = render_template(f)
    held = [{"facts": f, "good": good, "text": good.replace("prograde", "retrograde")}]
    rep = guard_eval.evaluate(6, 2, heldout=held, real_briefs=[{"facts": f, "text": good}], guardian_n=4, guard_fn=fake)
    assert rep["guardian"]["quant"] == "Q8_0" and rep["guardian"]["latency_ms"]["brief"]["mean"] == 5.0
    assert rep["results"]["synthetic_non_numeric"]["guardian"]["n"] == 4
    assert rep["results"]["heldout_llm"]["claims"]["n"] == 1
    assert rep["results"]["false_flags_real_granite_briefs"]["claims"]["k"] == 0


def test_guardian_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("GUARDIAN_MODE", raising=False)
    monkeypatch.setenv(guardian.ENV_PATH, "/m/g.gguf")
    assert guardian.run_configured("c", "r") == {"status": "off", "mode": "off"}
    monkeypatch.setenv("GUARDIAN_MODE", "sentence")
    with pytest.raises(ValueError):
        guardian.run_configured("c", "r")


def test_cli_writes_json(tmp_path, monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    out = tmp_path / "ge.json"
    assert guard_eval.main(["--n", "5", "--seed", "3", "--heldout", "0", "--real", "0", "--out", str(out)]) == 0
    d = json.loads(out.read_text())
    assert d["n_per_class"] == 5 and d["platform"]["machine"] and "Q4_K_M" in " ".join(d["notes"])


def test_claims_accept_short_object_name_but_flag_swaps():
    from orbitguard.brief.claims import check_claims
    facts = {"event": {"primary": {"norad": 25544, "name": "ISS (ZARYA)"},
                       "threat": {"norad": 64962, "name": "ENSHI XIDA SHANQUAN"}}}
    ok = "The ISS (NORAD 25544) passes ENSHI XIDA SHANQUAN (NORAD 64962)."
    swapped = "ENSHI XIDA SHANQUAN (NORAD 25544) passes the ISS (NORAD 64962)."
    assert not [i for i in check_claims(ok, facts) if i.startswith("object")]
    assert [i for i in check_claims(swapped, facts) if i.startswith("object")]


def test_claims_accept_spelled_out_station_name():
    from orbitguard.brief.claims import check_claims
    facts = {"event": {"primary": {"norad": 25544, "name": "ISS (ZARYA)"},
                       "threat": {"norad": 64962, "name": "ENSHI XIDA SHANQUAN"}}}
    text = "The International Space Station (NORAD 25544) will pass ENSHI XIDA SHANQUAN (NORAD 64962)."
    assert not [i for i in check_claims(text, facts) if i.startswith("object")]
