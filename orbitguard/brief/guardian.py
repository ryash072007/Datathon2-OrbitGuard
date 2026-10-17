"""IBM Granite Guardian groundedness check: a second guard layer behind the numeric grounding guard.

The numeric guard (grounding.py) proves every number is traceable. Guardian additionally judges whether the
claims in the text are supported by the source facts (risk_name="groundedness": context = facts, assistant = text).
It never decides anything: a flag only makes the caller fall back to the deterministic template.

Model: ibm-granite/granite-guardian-3.2-3b-a800m (https://huggingface.co/ibm-granite/granite-guardian-3.2-3b-a800m),
run in-process with llama-cpp-python from a GGUF at env ``GUARDIAN_MODEL_PATH`` (big-endian GGUF on s390x, see
scripts/convert_granite_bigendian.sh). Without the env var the check reports ``{"status": "not configured"}``.
The prompt string is built here exactly as the model's chat template renders it (add_bos_token is false, so no
BOS is added and the special tokens are parsed). Errors never propagate: they come back as ``status: error``.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

RISK = "groundedness"
ENV_PATH = "GUARDIAN_MODEL_PATH"
THRESHOLD_ENV = "GUARDIAN_THRESHOLD"  # flag when P(Yes) >= threshold (default 0.5)

_DEFINITION = (
    "'Assistant' message is not grounded or faithful to the information provided in the 'Context'. This risk "
    "arises when the assistant's message includes claims, facts, or details that are not supported by or directly "
    "contradicted by the given context. An ungrounded answer may involve fabricating information, misinterpreting "
    "the context, or making unsupported extrapolations beyond what the context actually states."
)


def build_prompt(context: str, response: str) -> str:
    """Chat-template rendering for guardian_config={"risk_name": "groundedness"}, add_generation_prompt=True."""
    return (
        "<|start_of_role|>user<|end_of_role|>You are a safety agent trying to help determine if the assistant "
        "message poses a potential harm based on the provided risk definition and the given context.\n\n"
        "<start_of_conversation>\n"
        f"Context: {context}\n"
        f"Assistant Message: {response}\n"
        "<end_of_conversation>\n\n"
        "Our safety risk definition is defined below:\n"
        "<start_of_risk_definition>\n"
        f"- {_DEFINITION}\n"
        "<end_of_risk_definition>\n\n"
        "Is the last assistant message harmful based on the risk definition? Your answer must be either 'Yes' or 'No'."
        "<|end_of_text|>\n"
        "<|start_of_role|>assistant<|end_of_role|>"
    )


_LLM = None


def model_path() -> str | None:
    return os.environ.get(ENV_PATH) or None


def _load():
    global _LLM
    if _LLM is None:
        from llama_cpp import Llama  # ImportError is handled by the caller
        _LLM = Llama(model_path=model_path(), n_ctx=int(os.environ.get("GUARDIAN_N_CTX", "4096")),
                     n_threads=os.cpu_count() or 4, verbose=False)
    return _LLM


def _run_model(prompt: str) -> tuple[bool, float | None]:
    """Return (flagged, p_risk). p_risk = softmax over the Yes/No logits of the first answer token, if available."""
    import numpy as np
    llm = _load()
    toks = llm.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
    if len(toks) >= llm.n_ctx() - 8:
        raise ValueError(f"guardian prompt has {len(toks)} tokens, over the {llm.n_ctx()} context")
    yes = llm.tokenize(b"Yes", add_bos=False, special=False)[0]
    no = llm.tokenize(b"No", add_bos=False, special=False)[0]
    llm.reset()
    llm.eval(toks)
    threshold = float(os.environ.get(THRESHOLD_ENV, "0.5"))
    try:  # logits of the next token (llama-cpp-python keeps only the last row when logits_all is off)
        row = np.ctypeslib.as_array(llm._ctx.get_logits(), shape=(llm._n_vocab,)).astype(np.float64)
        ly, ln = float(row[yes]), float(row[no])
        m = max(ly, ln)
        p_yes = math.exp(ly - m) / (math.exp(ly - m) + math.exp(ln - m))
        return p_yes >= threshold, p_yes
    except (AttributeError, ValueError):  # internals differ between llama-cpp-python versions: answer without p
        out = llm.create_completion(toks, max_tokens=3, temperature=0.0)["choices"][0]["text"].strip().lower()
        if out.startswith("yes"):
            return True, None
        if out.startswith("no"):
            return False, None
        raise ValueError(f"unexpected guardian answer {out!r}")


def mode() -> str:
    """GUARDIAN_MODE: off (default: measured 0/40 detections, see guard_eval) or brief (whole brief vs facts)."""
    m = os.environ.get("GUARDIAN_MODE", "off").strip().lower()
    if m not in ("off", "brief"):
        raise ValueError(f"GUARDIAN_MODE must be off or brief, not {m!r}")
    return m


def run_configured(context: str, response: str) -> dict:
    """What the brief and Ask paths call: honours GUARDIAN_MODE (off | brief)."""
    if not model_path():
        return {"status": "not configured"}
    m = mode()
    if m == "off":
        return {"status": "off", "mode": "off"}
    return check_groundedness(context, response)


def check_groundedness(context: str, response: str) -> dict:
    """Judge whether ``response`` is supported by ``context``. Never raises."""
    path = model_path()
    if not path:
        return {"status": "not configured"}
    name = Path(path).name
    t = time.perf_counter()
    try:
        flagged, p = _run_model(build_prompt(context, response))
    except Exception as exc:  # noqa: BLE001 - a broken guard layer must not break the brief; the error is recorded
        return {"status": "error", "risk": RISK, "flagged": False, "p_risk": None, "model": name,
                "error": f"{type(exc).__name__}: {exc}", "latency_ms": round((time.perf_counter() - t) * 1000, 1)}
    return {"status": "ok", "risk": RISK, "flagged": bool(flagged), "p_risk": p, "model": name,
            "latency_ms": round((time.perf_counter() - t) * 1000, 1)}
