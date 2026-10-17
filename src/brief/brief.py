"""Brief generation with a grounding guard and a deterministic template fallback."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .backends import Backend, build_prompt, get_backend
from .grounding import check_grounding
from .template import render_template


@dataclass
class Brief:
    text: str
    backend_used: str
    grounded: bool
    issues: list[str] = field(default_factory=list)


def make_brief_from_facts(facts: dict, backend: Backend | str | None = None) -> Brief:
    """Generate with the selected backend; fall back to the template if it errors or is ungrounded."""
    issues: list[str] = []
    name = backend if isinstance(backend, str) else getattr(backend, "name", None)
    try:
        be = backend if isinstance(backend, Backend) else get_backend(backend)
        name = be.name
        if name != "template":
            text = be.generate(build_prompt(facts), facts)
            bad = check_grounding(text, facts)
            if not bad:
                return Brief(text, name, True, [])
            issues.append(f"fallback: {name} output had ungrounded numbers {bad}")
        else:
            text = be.generate("", facts)
            bad = check_grounding(text, facts)
            return Brief(text, "template", not bad, [f"ungrounded numbers {bad}"] if bad else [])
    except Exception as exc:  # noqa: BLE001 - any backend failure must degrade to the template, and is recorded
        issues.append(f"fallback: {name or 'backend'} failed: {type(exc).__name__}: {exc}")
    text = render_template(facts)
    bad = check_grounding(text, facts)
    return Brief(text, "template", not bad, issues + ([f"ungrounded numbers {bad}"] if bad else []))


def make_brief(event: dict, risk: float, ranked: pd.DataFrame) -> str:
    """Contract: event + predicted log10 Pc + ranked burns -> brief text."""
    cols = [c for c in ("burn_id", "direction", "dv_mps", "miss_km_threat", "new_conjunctions", "feasible",
                        "lead_periods") if c in ranked.columns]
    top = ranked[cols].head(3).to_dict("records")
    facts = {"event": event, "risk": {"predicted_log10_pc": risk}, "burns": {"top": top}}
    return make_brief_from_facts(facts).text
