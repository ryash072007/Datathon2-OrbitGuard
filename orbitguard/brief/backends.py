"""Brief generators behind one interface: ``generate(prompt, facts) -> str``.

Selected by env ``LLM_BACKEND``: ``template`` (default), ``llamacpp`` or ``openai`` (any OpenAI-compatible
HTTP endpoint: llama.cpp server, Ollama, a watsonx gateway). Real backends are only imported / contacted
when ``generate`` is called, so the template path has no extra dependencies.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SYSTEM_PROMPT = (
    "You are a space-operations analyst writing a decision-support brief for a satellite operator. "
    "The operator decides; you never command. Use ONLY the facts in the JSON. Copy every number exactly as "
    "it appears in the JSON (the display strings), never compute, convert or invent numbers, and do not "
    "number your sections. Write markdown with exactly these six headings in this order: "
    "## Situation, ## Risk, ## Options, ## Consequence if no action, ## Recommendation, ## Uncertainties. "
    "Situation: names, NORAD ids, closest-approach time, miss distance. Risk: collision probability, its "
    "worst case and its caveat. Options: one bullet per burn in 'burns' (id, direction, delta-v, miss, new close "
    "approaches, worst-case Pc) then one trade-off sentence. Consequence: fragments and satellites exposed. "
    "Recommendation: restate 'recommendation' exactly (if its status is abstained, say escalate; never pick a "
    "different burn), and if 'pair_only_comparison' shows a secondary hazard, say so in one sentence. "
    "Uncertainties: two short sentences. Maximum 230 words."
)


def _f(x, nd: int) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x)


def llm_view(facts: dict) -> dict:
    """Compact facts for the LLM: only what the brief needs, key numbers pre-formatted as display strings."""
    ev = facts.get("event", {})
    p, t = ev.get("primary", {}), ev.get("threat", {})
    risk, burns, cons = facts.get("risk", {}), facts.get("burns", {}), facts.get("consequence") or {}
    view: dict = {
        "primary": f"{p.get('name')} (NORAD {p.get('norad')})", "threat": f"{t.get('name')} (NORAD {t.get('norad')})",
        "closest_approach_utc": ev.get("tca_utc"), "miss_km": _f(ev.get("miss_km"), 2),
        "collision_probability": f"{risk['live_pc']:.1e}" if risk.get("live_pc") is not None else None,
        "collision_probability_worst_case": f"{risk['live_pc_worst']:.1e}" if risk.get("live_pc_worst") is not None else None,
        "probability_caveat": risk.get("pc_note"),
        "no_burn_miss_km": _f(burns.get("baseline_miss_km"), 2), "target_miss_km": _f(burns.get("target_km"), 0),
        "burns": [{"id": b.get("burn_id"), "direction": b.get("direction"), "delta_v_m_per_s": _f(b.get("dv_mps"), 2),
                   "miss_km": _f(b.get("miss_km_threat"), 1), "new_close_approaches": b.get("new_conjunctions"),
                   "meets_target": "yes" if b.get("feasible") else "no",
                   "worst_case_pc": f"{b['worst_pc']:.1e}" if b.get("worst_pc") is not None else None}
                  for b in burns.get("top", [])[:3]],
    }
    pol = burns.get("policies") or {}
    if pol.get("status"):
        og, pair = pol.get("orbitguard") or {}, pol.get("pair_only") or {}
        view["recommendation"] = {"status": pol["status"], "burn": og.get("burn_id"),
                                  "delta_v_m_per_s": _f(og.get("dv_mps"), 2) if og else None,
                                  "pc_threshold": f"{pol['pc_threshold']:.0e}", "reason": pol.get("reason")}
        if pair.get("introduced_secondary_hazard"):
            view["pair_only_comparison"] = {"burn": pair.get("burn_id"), "other_object_norad": pair.get("worst_other_norad"),
                                            "other_object_pc": f"{pair['worst_other_pc']:.1e}"}
    if cons:
        view["consequence"] = {
            "catastrophic": "yes" if cons.get("catastrophic") else "no",
            "fragments_over_10cm": f"{cons['fragments_true']:,.0f}" if cons.get("fragments_true") is not None else None,
            "satellites_with_encounter": f"{cons.get('n_sats_ge1_encounter'):,}",
            "satellites_considered": f"{cons.get('n_sats_considered'):,}",
            "horizon_days": (cons.get("assumptions") or {}).get("horizon_days")}
    return view


def build_prompt(facts: dict) -> str:
    return SYSTEM_PROMPT + "\n\nFACTS (JSON):\n" + json.dumps(llm_view(facts), separators=(",", ":"), default=str)


class Backend:
    name = "base"

    def generate(self, prompt: str, facts: dict) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class TemplateBackend(Backend):
    name = "template"

    def generate(self, prompt: str, facts: dict) -> str:
        from .template import render_template
        return render_template(facts)


class LlamaCppBackend(Backend):
    name = "llamacpp"
    _llm = None

    def generate(self, prompt: str, facts: dict) -> str:
        path = os.environ.get("LLM_MODEL_PATH")
        if not path:
            raise RuntimeError("LLM_BACKEND=llamacpp needs LLM_MODEL_PATH (path to a GGUF file)")
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError("llama_cpp_python is not installed in this environment "
                               "(it ships in the LinuxONE Jupyter ML image)") from exc
        if LlamaCppBackend._llm is None:
            LlamaCppBackend._llm = Llama(model_path=path, n_ctx=max(4096, int(os.environ.get("LLM_N_CTX", "4096"))),
                                         n_threads=os.cpu_count() or 4, verbose=False)
        system, _, user = prompt.partition("\n\nFACTS (JSON):\n")
        out = LlamaCppBackend._llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": "FACTS (JSON):\n" + user}],
            temperature=0.2, max_tokens=700)
        return out["choices"][0]["message"]["content"].strip()


class OpenAIBackend(Backend):
    name = "openai"

    def generate(self, prompt: str, facts: dict) -> str:
        base = os.environ.get("LLM_BASE_URL")
        model = os.environ.get("LLM_MODEL")
        if not base or not model:
            raise RuntimeError("LLM_BACKEND=openai needs LLM_BASE_URL and LLM_MODEL")
        system, _, user = prompt.partition("\n\nFACTS (JSON):\n")
        body = json.dumps({"model": model, "temperature": 0.0, "max_tokens": 600, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": "FACTS (JSON):\n" + user}]}).encode()
        headers = {"Content-Type": "application/json"}
        if os.environ.get("LLM_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["LLM_API_KEY"]
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=float(os.environ.get("LLM_TIMEOUT_S", "120"))) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"LLM endpoint {base} failed: {exc}") from exc
        return data["choices"][0]["message"]["content"].strip()


BACKENDS: dict[str, type[Backend]] = {"template": TemplateBackend, "llamacpp": LlamaCppBackend,
                                      "openai": OpenAIBackend}


def get_backend(name: str | None = None) -> Backend:
    name = (name or os.environ.get("LLM_BACKEND") or "template").strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"unknown LLM_BACKEND {name!r}; choose one of {sorted(BACKENDS)}")
    return BACKENDS[name]()
