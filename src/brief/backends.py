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
    "You are a space-operations analyst writing a human-in-the-loop decision brief for a satellite operator. "
    "Use ONLY the facts in the JSON provided and never invent or compute new numbers; every number you write "
    "must appear in the JSON (rounding is fine). You support the decision, you do not make it. "
    "Write markdown with exactly these sections: Situation, Risk, Options (the top 3 burns with trade-offs), "
    "Consequence if no action, Recommendation, Uncertainties. Maximum 250 words."
)


def build_prompt(facts: dict) -> str:
    return SYSTEM_PROMPT + "\n\nFACTS (JSON):\n" + json.dumps(facts, separators=(",", ":"), default=str)


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
            LlamaCppBackend._llm = Llama(model_path=path, n_ctx=int(os.environ.get("LLM_N_CTX", "4096")),
                                         verbose=False)
        system, _, user = prompt.partition("\n\nFACTS (JSON):\n")
        out = LlamaCppBackend._llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": "FACTS (JSON):\n" + user}],
            temperature=0.0, max_tokens=600)
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
