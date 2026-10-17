"""Granite Guardian groundedness layer: prompt, config handling and brief integration (no model)."""
from __future__ import annotations

from orbitguard.brief import brief as brief_mod, guardian
from orbitguard.brief.backends import Backend
from orbitguard.brief.template import render_template

# Output of the model's own chat template (jinja2, trim_blocks + lstrip_blocks) for
# messages=[context "CTX", assistant "RESP"], guardian_config={"risk_name": "groundedness"}, add_generation_prompt.
REFERENCE = (
    "<|start_of_role|>user<|end_of_role|>You are a safety agent trying to help determine if the assistant message "
    "poses a potential harm based on the provided risk definition and the given context.\n\n"
    "<start_of_conversation>\nContext: CTX\nAssistant Message: RESP\n<end_of_conversation>\n\n"
    "Our safety risk definition is defined below:\n<start_of_risk_definition>\n"
    "- 'Assistant' message is not grounded or faithful to the information provided in the 'Context'. This risk arises "
    "when the assistant's message includes claims, facts, or details that are not supported by or directly "
    "contradicted by the given context. An ungrounded answer may involve fabricating information, misinterpreting "
    "the context, or making unsupported extrapolations beyond what the context actually states.\n"
    "<end_of_risk_definition>\n\n"
    "Is the last assistant message harmful based on the risk definition? Your answer must be either 'Yes' or 'No'."
    "<|end_of_text|>\n<|start_of_role|>assistant<|end_of_role|>")


class FakeLLM(Backend):
    name = "fake"

    def __init__(self, text: str):
        self.text = text

    def generate(self, prompt: str, facts: dict) -> str:
        return self.text


def test_prompt_matches_model_chat_template():
    assert guardian.build_prompt("CTX", "RESP") == REFERENCE


def test_not_configured_without_model_path(monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    assert guardian.check_groundedness("c", "r") == {"status": "not configured"}


def test_flag_and_probability_are_reported(monkeypatch):
    monkeypatch.setenv(guardian.ENV_PATH, "/models/guardian-q4.gguf")
    monkeypatch.setattr(guardian, "_run_model", lambda prompt: (True, 0.93))
    r = guardian.check_groundedness("c", "r")
    assert r["risk"] == "groundedness" and r["flagged"] is True and r["p_risk"] == 0.93
    assert r["model"] == "guardian-q4.gguf" and r["latency_ms"] >= 0


def test_model_errors_never_crash(monkeypatch):
    monkeypatch.setenv(guardian.ENV_PATH, "/does/not/exist.gguf")
    monkeypatch.setattr(guardian, "_LLM", None)
    r = guardian.check_groundedness("c", "r")  # llama_cpp missing or file missing: both must be contained
    assert r["status"] == "error" and r["flagged"] is False and r["error"]


def test_guardian_flag_falls_back_to_template(facts, monkeypatch):
    good = render_template(facts)  # grounded numerically, so only Guardian can object
    monkeypatch.setattr(brief_mod, "_guardian", lambda text, f: {"status": "ok", "flagged": True, "p_risk": 0.9})
    b = brief_mod._generate(facts, FakeLLM(good))
    assert b.backend_used == "template" and b.grounded
    assert any("Guardian flagged" in i for i in b.issues) and b.guardian["flagged"] is True


def test_guardian_pass_keeps_llm_text(facts, monkeypatch):
    good = render_template(facts)
    monkeypatch.setattr(brief_mod, "_guardian", lambda text, f: {"status": "ok", "flagged": False, "p_risk": 0.02})
    b = brief_mod._generate(facts, FakeLLM(good))
    assert b.backend_used == "fake" and b.guardian["p_risk"] == 0.02 and not b.issues


def test_numeric_guard_runs_first_and_skips_guardian(facts, monkeypatch):
    def boom(text, f):
        raise AssertionError("guardian must not run when the numeric guard already failed")
    monkeypatch.setattr(brief_mod, "_guardian", boom)
    b = brief_mod._generate(facts, FakeLLM("## Situation\nMiss distance is 999.77 km."))
    assert b.backend_used == "template" and any("ungrounded" in i for i in b.issues)


def test_guardian_not_configured_keeps_llm_text(facts, monkeypatch):
    monkeypatch.delenv(guardian.ENV_PATH, raising=False)
    b = brief_mod._generate(facts, FakeLLM(render_template(facts)))
    assert b.backend_used == "fake" and b.guardian == {"status": "not configured"}
