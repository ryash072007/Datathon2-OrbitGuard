"""Brief template, grounding guard and backend fallback (fake backends only, no real model)."""
from __future__ import annotations

import pytest

from src.brief.backends import Backend, get_backend
from src.brief.brief import make_brief_from_facts
from src.brief.grounding import check_grounding
from src.brief.template import render_template


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, text: str | None = None, error: Exception | None = None):
        self.text, self.error = text, error

    def generate(self, prompt: str, facts: dict) -> str:
        if self.error:
            raise self.error
        return self.text


def test_template_is_always_grounded(facts):
    text = render_template(facts)
    assert check_grounding(text, facts) == []
    b = make_brief_from_facts(facts)
    assert b.backend_used == "template" and b.grounded and b.issues == []
    for section in ("Situation", "Risk", "Options", "Consequence if no action", "Recommendation", "Uncertainties"):
        assert f"## {section}" in text


def test_template_handles_sparse_facts():
    sparse = {"event": {"primary": {"name": "A", "norad": 1}, "threat": {"name": "B", "norad": 2}, "tca_utc": "t",
                        "miss_km": 1.5}}
    assert "## Situation" in render_template(sparse)


def test_guard_catches_invented_number(facts):
    bad = check_grounding("The miss distance is 4.98 km but the collision chance is 77.7 percent.", facts)
    assert bad == ["77.7"]


def test_guard_accepts_rounded_and_formatted_numbers(facts):
    text = ("Miss 5.0 km, about 4.98 km. Pc 8.3e-10 (0.00000000083). Fragments about 11,300 or 11259; "
            "8,943 of 15,145 satellites; 34% re-enter; ejected 28.5 t; speed 7600 m/s; log10 Pc -6.38.")
    assert check_grounding(text, facts) == []


def test_guard_ignores_dates_and_list_numbers(facts):
    assert check_grounding("1. First option at 2026-10-18T04:48:38+00:00\n2. Second", facts) == []


def test_fallback_on_ungrounded_output(facts):
    b = make_brief_from_facts(facts, FakeBackend("Collision chance is 1234.5 percent."))
    assert b.backend_used == "template" and b.grounded
    assert any("1234.5" in i for i in b.issues)


def test_fallback_on_backend_error(facts):
    b = make_brief_from_facts(facts, FakeBackend(error=RuntimeError("endpoint down")))
    assert b.backend_used == "template" and b.grounded
    assert any("endpoint down" in i for i in b.issues)


def test_grounded_llm_output_is_used(facts):
    b = make_brief_from_facts(facts, FakeBackend("Miss distance is 4.98 km for ISS (ZARYA)."))
    assert b.backend_used == "fake" and b.grounded and b.issues == []


def test_backend_selection(monkeypatch, facts):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert get_backend().name == "template"
    monkeypatch.setenv("LLM_BACKEND", "openai")
    assert get_backend().name == "openai"
    with pytest.raises(ValueError):
        get_backend("nope")
    # missing configuration -> recorded fallback, brief still produced
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    b = make_brief_from_facts(facts)
    assert b.backend_used == "template" and any("LLM_BASE_URL" in i for i in b.issues)
    b = make_brief_from_facts(facts, "does-not-exist")
    assert b.backend_used == "template" and b.issues
