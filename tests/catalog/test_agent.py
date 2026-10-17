"""Ask OrbitGuard agent: tool loop, caps, grounding and Guardian fallbacks, API route (no model)."""
from __future__ import annotations

import json

import pytest

from orbitguard.api import create_app
from orbitguard.brief import agent, guardian


def _policy_row(top, **extra):
    keys = ("burn_id", "direction", "dv_mps", "lead_periods", "miss_km_threat", "new_conjunctions", "feasible",
            "worst_pc", "worst_other_norad", "accepted")
    return {**{k: top.get(k) for k in keys}, **extra}


@pytest.fixture
def cached(data_fixture, facts):
    top = facts["burns"]["top"]
    for r, (wp, acc) in zip(top, [(2e-6, True), (5e-5, True), (3e-3, False)]):
        r.update(worst_pc=wp, accepted=acc, worst_other_norad=40001)
    facts["risk"]["live_pc_worst"] = 2.5e-9
    facts["burns"].update(pc_threshold=1e-4, n_accepted=2, policies={
        "status": "recommended", "reason": "Lowest delta-v candidate.", "pc_threshold": 1e-4,
        "orbitguard": _policy_row(top[0]), "no_action": None,
        "pair_only": _policy_row(top[2], introduced_secondary_hazard=True, worst_other_pc=3e-3)})
    (data_fixture / "out" / "facts_25544.json").write_text(json.dumps(facts), encoding="utf-8")
    return data_fixture


class Scripted:
    """Fake LLM: returns the next scripted JSON string per step (the schema is ignored)."""
    name = "llamacpp"

    def __init__(self, *steps):
        self.steps, self.i, self.seen = list(steps), 0, []

    def chat(self, messages, schema):
        self.seen.append(messages)
        out = self.steps[min(self.i, len(self.steps) - 1)]
        self.i += 1
        return out if isinstance(out, str) else json.dumps(out)


def test_template_later_orbit_routes_to_lookup_burn(cached):
    r = agent.ask("what if I burn one orbit later?", 25544)
    assert r["backend"] == "template" and r["grounded"] and r["fallback_reason"] is None
    [call] = r["tool_calls"]
    assert call["tool"] == "lookup_burn" and call["args"]["lead_orbits"] == 2.0 and call["args"]["direction"] == "+T"
    assert "+T_0.5_2P" in r["answer"] and "accepted" in r["answer"] and "15.3 km" in r["answer"]
    assert r["guardian"]["status"].startswith("not applicable")


def test_template_routes_other_questions(cached):
    assert agent.ask("did the pair-only check miss something?", 25544)["tool_calls"][0]["tool"] == "compare_pair_only"
    assert agent.ask("how much debris would it make?", 25544)["tool_calls"][0]["tool"] == "consequence_summary"
    assert agent.ask("show the audit log", 25544)["tool_calls"][0]["tool"] == "recent_audit"
    r = agent.ask("what is going on?", 25544)
    assert r["tool_calls"][0]["tool"] == "get_event_facts" and "DEBRIS ONE" in r["answer"]


def test_rejected_burn_reports_why(cached):
    r = agent.ask("what about a -T burn at 0.5 m/s?", None)
    assert "rejected" in r["answer"] and "exceeds" in r["answer"] and r["grounded"]


def test_uncached_burn_is_stated_not_invented(cached):
    r = agent.ask("what about a +N burn of 0.01 m/s?", 25544)
    assert "not among the screened candidates" in r["answer"] and r["grounded"]


def test_ask_is_audited(cached):
    from orbitguard.audit.log import tail, verify_log
    agent.ask("what if I burn one orbit later?", 25544)
    rec = tail(1)[0]
    assert rec["kind"] == "ask" and rec["payload"]["tools"] == ["lookup_burn"]
    assert len(rec["payload"]["answer_sha256"]) == 64 and verify_log()[0]


def test_llm_tool_loop_and_grounded_answer(cached):
    be = Scripted({"tool": "get_event_facts", "args": {}},
                  {"tool": "lookup_burn", "args": {"direction": "+T", "dv_mps": 0.5, "lead_orbits": 2.0}},
                  {"answer": "A +T burn of 0.5 m/s two orbits before closest approach gives a miss of 15.3 km."})
    r = agent.ask("what if I burn one orbit later?", 25544, be)
    assert [c["tool"] for c in r["tool_calls"]] == ["get_event_facts", "lookup_burn"]
    assert r["backend"] == "llamacpp" and r["grounded"] and r["fallback_reason"] is None
    assert "TOOL RESULT (lookup_burn)" in be.seen[-1][-1]["content"]


def test_max_tool_calls_cap_falls_back(cached):
    be = Scripted({"tool": "get_event_facts", "args": {}})  # never answers
    r = agent.ask("tell me everything", 25544, be)
    assert len(r["tool_calls"]) == agent.MAX_TOOL_CALLS and be.i == agent.MAX_TOOL_CALLS + 1
    assert r["backend"] == "template" and "cap" in r["fallback_reason"] and r["grounded"]


def test_invented_number_falls_back_to_tool_answer(cached):
    be = Scripted({"tool": "lookup_burn", "args": {"direction": "+T", "dv_mps": 0.5, "lead_orbits": 2.0}},
                  {"answer": "That burn gives a miss of 48.7 km."})
    r = agent.ask("what if I burn one orbit later?", 25544, be)
    assert r["backend"] == "template" and "ungrounded numbers" in r["fallback_reason"] and "48.7" in r["fallback_reason"]
    assert "48.7" not in r["answer"] and "15.3 km" in r["answer"] and r["grounded"]


@pytest.mark.parametrize("steps", [["not json"], [{"answer": "no tools used"}], [{"tool": "launch_burn", "args": {}}]])
def test_bad_model_output_falls_back(cached, steps):
    r = agent.ask("what if I burn one orbit later?", 25544, Scripted(*steps))
    assert r["backend"] == "template" and r["fallback_reason"] and r["grounded"] and r["tool_calls"]


def test_guardian_flag_falls_back_to_template(cached, monkeypatch):
    monkeypatch.setenv(guardian.ENV_PATH, "/models/g.gguf")
    monkeypatch.setenv("GUARDIAN_MODE", "brief")
    monkeypatch.setattr(guardian, "_run_model", lambda prompt: (True, 0.88))
    be = Scripted({"tool": "get_event_facts", "args": {}}, {"answer": "The miss distance is 4.98 km."})
    r = agent.ask("how close?", 25544, be)
    assert r["backend"] == "template" and "Guardian" in r["fallback_reason"]
    assert r["guardian"]["flagged"] is True and r["grounded"]


def test_guardian_absent_is_reported_and_answer_kept(cached, monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    be = Scripted({"tool": "get_event_facts", "args": {}}, {"answer": "The miss distance is 4.98 km."})
    r = agent.ask("how close?", 25544, be)
    assert r["backend"] == "llamacpp" and r["guardian"] == {"status": "not configured"}


def test_input_validation_and_missing_cache(cached):
    for bad in ("", "x" * 501, 7):
        with pytest.raises(ValueError):
            agent.ask(bad, 25544)
    with pytest.raises(ValueError):
        agent.ask("hi", True)
    with pytest.raises(FileNotFoundError):
        agent.ask("hi", 99999)


def test_unknown_tool_args_and_bad_direction_are_contained(cached):
    ctx = agent.Context(25544)
    assert "error" in agent.run_tool(ctx, "lookup_burn", {"direction": "sideways"})
    assert agent.run_tool(ctx, "get_event_facts", {"bogus": 1})["primary"]["norad"] == 25544
    with pytest.raises(ValueError):
        agent.run_tool(ctx, "launch_burn", {})


@pytest.fixture
def client(cached, tmp_path):
    class Stub:
        def evidence(self):
            return {"status": "missing"}
    return create_app(tmp_path, ml_service=Stub(), physics_service=Stub()).test_client()


def test_api_ask_route(client):
    r = client.post("/api/live/ask", json={"question": "what if I burn one orbit later?", "norad": 25544})
    assert r.status_code == 200
    j = r.get_json()
    assert j["grounded"] and j["tool_calls"][0]["tool"] == "lookup_burn" and "guardian" in j
    assert client.post("/api/live/ask", json={"question": "audit log?"}).status_code == 200


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x" * 501}, {"question": 5},
                                     {"question": "hi", "norad": "25544"}, {"question": "hi", "norad": True},
                                     {"question": "hi", "norad": -1}])
def test_api_ask_validates_input(client, payload):
    assert client.post("/api/live/ask", json=payload).status_code == 422


def test_api_ask_without_analysis_is_not_ready(client):
    assert client.post("/api/live/ask", json={"question": "hi", "norad": 99999}).status_code == 503


def test_full_burn_table_is_searchable_but_not_a_brief_fact(cached, facts):
    from orbitguard.brief.brief import make_brief_from_facts
    extra = {"burn_id": "+N_0.01_1P", "direction": "+N", "dv_mps": 0.01, "lead_periods": 1.0, "miss_km_threat": 61.83,
             "new_conjunctions": 0, "feasible": False, "threat_pc_worst": 1e-7, "worst_pc": 1e-7,
             "worst_other_norad": None, "accepted": False}
    facts["burn_table"] = [extra]
    (cached / "out" / "facts_25544.json").write_text(json.dumps(facts), encoding="utf-8")
    r = agent.ask("what about a +N burn of 0.01 m/s?", 25544)
    assert "+N_0.01_1P" in r["answer"] and "does not meet" in r["answer"] and r["grounded"]
    # the table must not widen the brief's grounding set
    from orbitguard.brief.grounding import check_grounding
    assert check_grounding("The miss is 61.83 km.", {k: v for k, v in facts.items() if k != "burn_table"}) == ["61.83"]
    assert make_brief_from_facts(facts).grounded


def test_collect_facts_burn_table_columns():
    import pandas as pd
    from orbitguard.brief.facts import TABLE_COLUMNS, burn_table
    df = pd.DataFrame([{c: 1 for c in TABLE_COLUMNS}] * 3)
    assert len(burn_table(df)) == 3 and set(burn_table(df)[0]) == set(TABLE_COLUMNS)


def test_old_chain_with_brief_typed_asks_still_verifies(cached):
    from orbitguard.audit.log import KINDS, log_event, verify_log
    assert "ask" in KINDS
    log_event("brief", {"type": "ask", "question": "old style"})
    agent.ask("what is going on?", 25544)
    assert verify_log() == (True, None)


def test_template_answer_is_short_and_grounded_with_many_burn_rows(cached, facts):
    """Regression: 'Why not the pair-only burn?' on real data was flagged ungrounded and dumped five rows."""
    rows = [{"burn_id": f"+T_{dv:g}_{lead:g}P", "direction": "+T", "dv_mps": dv, "lead_periods": lead,
             "miss_km_threat": 11.0 + 7.3 * i, "new_conjunctions": i % 3, "feasible": True,
             "threat_pc_worst": 1e-7, "worst_pc": 3e-3 if i % 2 else 2e-6, "worst_other_norad": 40001,
             "accepted": i % 2 == 0}
            for i, (dv, lead) in enumerate([(0.01, 1.0), (0.02, 1.0), (0.05, 2.0), (0.1, 2.0), (0.2, 3.0), (0.5, 3.0)])]
    facts["burn_table"] = rows
    (cached / "out" / "facts_25544.json").write_text(json.dumps(facts), encoding="utf-8")
    r = agent.ask("Why not the pair-only burn?", 25544)
    assert r["grounded"] and [c["tool"] for c in r["tool_calls"]] == ["compare_pair_only"]
    r = agent.ask("Which +T burns work?", 25544)
    assert r["grounded"] and r["answer"].count("new close approaches") <= 3 and "first 3 shown" in r["answer"]
