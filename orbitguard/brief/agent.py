"""Ask OrbitGuard: an operator Q&A agent over deterministic, read-only tools.

The LLM (Granite 3.3 via llama-cpp-python, JSON forced by a schema grammar) only ROUTES a question to tools and
narrates their output. The tools read cached results of the live pipeline (``facts_<norad>.json``: event, screened
burn shortlist, Pc policies, consequence, network, and the audit chain). Nothing here changes a recommendation:

* the final answer passes the numeric grounding guard against the union of tool outputs, then Granite Guardian
  (if ``GUARDIAN_MODEL_PATH`` is set); any failure falls back to a deterministic answer built from the tool outputs;
* with no LLM the ``template`` backend routes by keyword to the same tools and answers from templates;
* every ask is appended to the audit chain (question, tools, grounded, sha256 of the answer).

CLI: ``python -m orbitguard.brief.agent --norad 25544 "what if I burn one orbit later?"``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from typing import Any, Callable

from .grounding import check_grounding

MAX_TOOL_CALLS = 3
MAX_QUESTION_CHARS = 500
DIRECTIONS = ("+T", "-T", "+R", "-R", "+N", "-N")
ISS_NORAD = 25544
DIRECTION_WORDS = {"+T": "prograde along-track", "-T": "retrograde along-track", "+R": "radial-out",
                   "-R": "radial-in", "+N": "cross-track (normal)", "-N": "cross-track (anti-normal)"}


# --------------------------------------------------------------------------- data access

class Context:
    """Cached facts for one primary. Tools get this; they never recompute or write."""

    def __init__(self, norad: int | None):
        from .facts import load_cached_facts
        if norad is None:
            norad = _default_norad()
        facts = load_cached_facts(norad)
        if facts is None:
            raise FileNotFoundError(f"no analysis for NORAD {norad}; POST /api/live/analyse first")
        self.norad, self.facts = norad, facts


def _default_norad() -> int:
    from orbitguard.live import _latest, _out
    if (_out() / f"facts_{ISS_NORAD}.json").exists():
        return ISS_NORAD
    p = _latest("facts_*.json")
    if p is None:
        raise FileNotFoundError("no cached live analysis; POST /api/live/analyse first")
    return int(p.stem.split("_", 1)[1])


def _f(x: Any, nd: int) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def _e(x: Any) -> str:
    return f"{x:.1e}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def _burn_rows(facts: dict) -> list[dict]:
    """Every screened burn row held in the cache: the shortlist plus the policy picks, de-duplicated."""
    burns = facts.get("burns", {})
    rows: dict[str, dict] = {}
    for r in burns.get("top", []):
        rows[r["burn_id"]] = r
    for key in ("orbitguard", "pair_only"):
        r = (burns.get("policies") or {}).get(key)
        if r and r.get("burn_id") and r["burn_id"] not in rows:
            rows[r["burn_id"]] = r
    return list(rows.values())


def _recommended(facts: dict) -> dict | None:
    pol = (facts.get("burns") or {}).get("policies") or {}
    og = pol.get("orbitguard")
    if og and og.get("direction") != "none":
        return og
    rows = _burn_rows(facts)
    return rows[0] if rows else None


def _why_rejected(r: dict, burns: dict) -> str | None:
    if r.get("accepted"):
        return None
    thr = burns.get("pc_threshold")
    if r.get("feasible") is False:
        return f"miss {_f(r.get('miss_km_threat'), 1)} km does not meet the {_f(burns.get('target_km'), 0)} km target"
    if r.get("worst_pc") is not None and thr is not None and r["worst_pc"] > thr:
        return (f"worst-case Pc {_e(r['worst_pc'])} over all close approaches exceeds the {_e(thr)} threshold"
                f" (worst object NORAD {r.get('worst_other_norad')})")
    if r.get("new_conjunctions"):
        return f"creates {r['new_conjunctions']} new close approach(es)"
    return "failed the all-object Pc check"


def _row_view(r: dict, burns: dict) -> dict:
    return {"burn_id": r.get("burn_id"), "direction": r.get("direction"), "dv_mps": r.get("dv_mps"),
            "lead_orbits": r.get("lead_periods"), "miss_km": r.get("miss_km_threat"),
            "new_close_approaches": r.get("new_conjunctions"), "meets_target": r.get("feasible"),
            "threat_pc_worst": r.get("threat_pc_worst", r.get("threat_pc")), "worst_pc": r.get("worst_pc"),
            "worst_other_norad": r.get("worst_other_norad"), "accepted": bool(r.get("accepted")),
            "why_rejected": _why_rejected(r, burns)}


# --------------------------------------------------------------------------- tools (read-only)

def get_event_facts(ctx: Context) -> dict:
    f = ctx.facts
    ev, risk, burns = f.get("event", {}), f.get("risk", {}), f.get("burns", {})
    pol = burns.get("policies") or {}
    og = pol.get("orbitguard") or {}
    rec = {"status": pol.get("status"), "reason": pol.get("reason")}
    if og:
        rec.update(burn_id=og.get("burn_id"), direction=og.get("direction"), dv_mps=og.get("dv_mps"),
                   lead_orbits=og.get("lead_periods"))
    return {"primary": {k: ev["primary"].get(k) for k in ("name", "norad")},
            "threat": {k: ev["threat"].get(k) for k in ("name", "norad")},
            "tca_utc": ev.get("tca_utc"), "miss_km": ev.get("miss_km"), "live_pc": risk.get("live_pc"),
            "live_pc_worst": risk.get("live_pc_worst"), "baseline_miss_km": burns.get("baseline_miss_km"),
            "target_km": burns.get("target_km"), "n_screened": burns.get("n_screened"),
            "n_accepted": burns.get("n_accepted"), "pc_threshold": burns.get("pc_threshold"), "recommendation": rec}


def lookup_burn(ctx: Context, direction: str | None = None, dv_mps: float | None = None,
                lead_orbits: float | None = None) -> dict:
    """Matching screened candidate rows from the cached table (absent filters match anything)."""
    burns = ctx.facts.get("burns", {})
    dirs: set[str] | None = None
    if direction is not None:
        d = str(direction).strip().upper().replace(" ", "")
        if d in DIRECTIONS:
            dirs = {d}
        elif d in ("R", "T", "N"):
            dirs = {"+" + d, "-" + d}
        else:
            raise ValueError(f"direction must be one of {DIRECTIONS} (or R, T, N for both signs)")
    rows = _burn_rows(ctx.facts)
    hit = [r for r in rows
           if (dirs is None or r.get("direction") in dirs)
           and (dv_mps is None or abs(float(r.get("dv_mps", -1)) - float(dv_mps)) < 1e-9)
           and (lead_orbits is None or abs(float(r.get("lead_periods", -1)) - float(lead_orbits)) < 1e-9)]
    hit.sort(key=lambda r: (not r.get("accepted"), r.get("dv_mps", 0), -(r.get("lead_periods") or 0)))
    out = {"requested": {"direction": direction, "dv_mps": dv_mps, "lead_orbits": lead_orbits},
           "matches": [_row_view(r, burns) for r in hit[:5]], "n_matches": len(hit),
           "n_cached_candidates": len(rows), "n_screened": burns.get("n_screened"),
           "pc_threshold": burns.get("pc_threshold"), "target_km": burns.get("target_km")}
    if not hit:
        out["note"] = ("not among the cached shortlisted candidates (the cache holds the best few of the screened "
                       "burns, not the whole table); rerun the live analysis to screen it")
        out["cached_burn_ids"] = [r["burn_id"] for r in rows]
    return out


def compare_pair_only(ctx: Context) -> dict:
    burns = ctx.facts.get("burns", {})
    pol = burns.get("policies") or {}
    pair, og = pol.get("pair_only"), pol.get("orbitguard")
    return {"status": pol.get("status"), "pc_threshold": pol.get("pc_threshold"),
            "pair_only": _row_view(pair, burns) if pair else None,
            "secondary_hazard": bool((pair or {}).get("introduced_secondary_hazard")),
            "other_object_norad": (pair or {}).get("worst_other_norad"),
            "other_object_pc": (pair or {}).get("worst_other_pc"),
            "orbitguard": _row_view(og, burns) if og and og.get("direction") != "none" else None,
            "reason": pol.get("reason")}


def consequence_summary(ctx: Context) -> dict:
    cons = ctx.facts.get("consequence")
    net = ctx.facts.get("network")
    out: dict = {"available": bool(cons)}
    if cons:
        exposed = sorted((cons.get("exposed_by_constellation") or {}).items(), key=lambda kv: -kv[1])[:3]
        out.update({k: cons.get(k) for k in ("catastrophic", "fragments_true", "n_sats_ge1_encounter",
                                             "n_sats_considered", "expected_harm")},
                   horizon_days=(cons.get("assumptions") or {}).get("horizon_days"),
                   top_exposed_constellations=[{"name": k, "satellites": v} for k, v in exposed])
    if net:
        out["network"] = {k: net.get(k) for k in ("n_objects", "primary", "threat")}
    return out


def recent_audit(ctx: Context, n: int = 5) -> dict:
    from orbitguard.audit.log import tail, verify_log
    n = max(1, min(int(n), 10))
    ok, bad = verify_log()
    entries = []
    for r in tail(n):
        p = r.get("payload") or {}
        entries.append({"seq": r.get("seq"), "utc": r.get("utc"), "kind": r.get("kind"),
                        "detail": p.get("choice") or p.get("type") or p.get("status") or p.get("backend")})
    return {"intact": ok, "first_bad_seq": bad, "entries": entries}


TOOLS: dict[str, tuple[Callable[..., dict], str]] = {
    "get_event_facts": (get_event_facts, "Event summary: objects, closest approach, miss, Pc, recommendation."),
    "lookup_burn": (lookup_burn, "Screened candidate burn(s) matching direction (+T,-T,+R,-R,+N,-N; optional), "
                                 "dv_mps (optional) and lead_orbits (orbits before closest approach, optional): "
                                 "miss km, worst-case Pc, accepted or why rejected."),
    "compare_pair_only": (compare_pair_only, "Pair-only pick versus the all-object OrbitGuard pick; secondary hazard."),
    "consequence_summary": (consequence_summary, "Debris/fragment consequence and network standing."),
    "recent_audit": (recent_audit, "Last n (1-10) entries of the hash-chained audit log and whether it is intact."),
}


def run_tool(ctx: Context, tool: str, args: dict | None) -> dict:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}; choose one of {sorted(TOOLS)}")
    args = dict(args or {})
    allowed = {"lookup_burn": {"direction", "dv_mps", "lead_orbits"}, "recent_audit": {"n"}}.get(tool, set())
    args = {k: v for k, v in args.items() if k in allowed and v is not None}
    try:
        return TOOLS[tool][0](ctx, **args)
    except (TypeError, ValueError) as exc:  # bad model arguments become a tool error the model/answer can see
        return {"error": f"{type(exc).__name__}: {exc}"}


def _summary(tool: str, res: dict) -> str:
    if "error" in res:
        return "error: " + res["error"][:120]
    if tool == "get_event_facts":
        return f"{res['primary']['name']} vs {res['threat']['name']}; recommendation {res['recommendation'].get('status')}"
    if tool == "lookup_burn":
        ids = [m["burn_id"] for m in res["matches"]]
        return f"{res['n_matches']} match(es): {', '.join(ids) or 'none cached'}"
    if tool == "compare_pair_only":
        return f"secondary hazard: {res['secondary_hazard']}; status {res['status']}"
    if tool == "consequence_summary":
        return "consequence available" if res.get("available") else "no consequence cached"
    return f"{len(res['entries'])} entries; chain intact: {res['intact']}"


# --------------------------------------------------------------------------- deterministic answers

def _fmt_row(m: dict) -> str:
    pc = f"; worst-case Pc {_e(m['worst_pc'])}" if m.get("worst_pc") is not None else ""
    lead = f", {m['lead_orbits']:g} orbits before closest approach" if m.get("lead_orbits") else ""
    verdict = "accepted" if m["accepted"] else f"rejected: {m['why_rejected']}"
    return (f"{m['burn_id']} ({DIRECTION_WORDS.get(m['direction'], m['direction'])}, {_f(m['dv_mps'], 2)} m/s{lead}): "
            f"miss {_f(m['miss_km'], 1)} km; {m['new_close_approaches']} new close approaches{pc}; {verdict}.")


def render_tool(tool: str, res: dict) -> str:
    if "error" in res:
        return f"The {tool} tool could not answer: {res['error']}."
    if tool == "get_event_facts":
        rec, p, t = res["recommendation"], res["primary"], res["threat"]
        if rec.get("status") == "recommended":
            recs = f"Recommended burn {rec['burn_id']} ({_f(rec['dv_mps'], 2)} m/s)."
        elif rec.get("status") == "no_action":
            recs = "No burn is needed."
        else:
            recs = "No acceptable burn in the evaluated set: escalate to the operator."
        pc = f" Collision probability {_e(res['live_pc'])} (worst case {_e(res['live_pc_worst'])})." \
            if res.get("live_pc") is not None else ""
        return (f"{p['name']} (NORAD {p['norad']}) closest approach with {t['name']} (NORAD {t['norad']}) at "
                f"{res['tca_utc']} UTC, miss {_f(res['miss_km'], 2)} km.{pc} {recs}")
    if tool == "lookup_burn":
        if not res["matches"]:
            return "No screened candidate matches that burn: it is " + res["note"] + "."
        head = f"{res['n_matches']} matching screened candidate(s)" + (
            f", showing {len(res['matches'])}" if res["n_matches"] > len(res["matches"]) else "") + ". "
        return head + " ".join(_fmt_row(m) for m in res["matches"])
    if tool == "compare_pair_only":
        pair, og = res["pair_only"], res["orbitguard"]
        s = "A pair-only check finds no acceptable burn. " if not pair else (
            f"A pair-only check would pick {pair['burn_id']} ({_f(pair['dv_mps'], 2)} m/s). ")
        if res["secondary_hazard"]:
            s += (f"That burn introduces a secondary hazard with NORAD {res['other_object_norad']} at Pc "
                  f"{_e(res['other_object_pc'])}, above the {_e(res['pc_threshold'])} threshold. ")
        elif pair:
            s += "It introduces no secondary hazard. "
        s += (f"OrbitGuard picks {og['burn_id']} ({_f(og['dv_mps'], 2)} m/s), checked against every close approach."
              if og else "OrbitGuard abstains: no candidate passes every close-approach check, so escalate to the operator.")
        return s
    if tool == "consequence_summary":
        if not res.get("available"):
            return "No consequence assessment is cached for this event."
        s = (f"If this collision occurred: about {_f(res['fragments_true'], 0)} fragments over 10 cm; "
             f"{res['n_sats_ge1_encounter']:,} of {res['n_sats_considered']:,} satellites would have at least one "
             f"close encounter within {_f(res['horizon_days'], 0)} days; "
             f"{'catastrophic' if res['catastrophic'] else 'non-catastrophic'} breakup.")
        if res.get("top_exposed_constellations"):
            s += " Most exposed: " + ", ".join(f"{c['name']} ({c['satellites']:,})"
                                               for c in res["top_exposed_constellations"]) + "."
        return s
    ents = res["entries"]
    kinds = ", ".join(f"{e['kind']} #{e['seq']}" for e in ents)
    return f"The audit chain is {'intact' if res['intact'] else 'BROKEN'}. Last {len(ents)} entries: {kinds or 'none'}."


def render_answer(calls: list[dict]) -> str:
    return " ".join(render_tool(c["tool"], c["result"]) for c in calls)


# --------------------------------------------------------------------------- keyword router (template backend)

_WORDS = {"one": 1, "a": 1, "an": 1, "another": 1, "two": 2, "three": 3, "half": 0.5, "1": 1, "2": 2, "3": 3}


def route(question: str, ctx: Context) -> list[tuple[str, dict]]:
    """Deterministic keyword routing to at most MAX_TOOL_CALLS (tool, args) pairs."""
    q = question.lower()
    plan: list[tuple[str, dict]] = []
    if re.search(r"audit|log\b|chain|history|recorded|operator decision", q):
        plan.append(("recent_audit", {"n": 5}))
    if re.search(r"pair|secondary|other object|second hazard", q):
        plan.append(("compare_pair_only", {}))
    if re.search(r"debris|fragment|consequence|harm|exposed|starlink|network|catastroph|satellites", q):
        plan.append(("consequence_summary", {}))
    if re.search(r"later|earlier|sooner|orbit|radial|along|track|prograde|retrograde|cross|normal|burn|m/s|delta|"
                 r"lead|[+-]\s?[rtn]\b", q):
        plan.append(("lookup_burn", _burn_args(q, ctx)))
    if not plan:
        plan.append(("get_event_facts", {}))
    return plan[:MAX_TOOL_CALLS]


def _burn_args(q: str, ctx: Context) -> dict:
    base = _recommended(ctx.facts) or {}
    args: dict = {}
    m = re.search(r"(?<![\w])([+-])\s?([rtn])(?![a-z])", q)
    if m:
        args["direction"] = (m.group(1) + m.group(2)).upper()
    elif re.search(r"retrograde", q):
        args["direction"] = "-T"
    elif re.search(r"prograde", q):
        args["direction"] = "+T"
    elif re.search(r"radial", q):
        args["direction"] = "R"
    elif re.search(r"cross|normal", q):
        args["direction"] = "N"
    elif re.search(r"along|track", q):
        args["direction"] = "T"
    d = re.search(r"(\d*\.?\d+)\s*m\s*/\s*s", q)
    if d:
        args["dv_mps"] = float(d.group(1))
    rel = re.search(r"(?:(\d+(?:\.\d+)?|one|two|three|half|a|an|another)\s+)?(?:orbit|period|revolution)s?\s*"
                    r"(later|earlier|sooner|before|after)", q)
    if rel is None and re.search(r"\b(later|earlier|sooner)\b", q):
        rel = re.search(r"\b(later|earlier|sooner)\b", q)
        n, way = 1.0, rel.group(1)
    elif rel is not None:
        n, way = float(_WORDS.get(rel.group(1) or "one", rel.group(1) or 1)), rel.group(2)
    else:
        n, way = None, None
    if way is not None and base.get("lead_periods") is not None:
        later = way in ("later", "after")
        args["lead_orbits"] = base["lead_periods"] + (-n if later else n)
        args.setdefault("direction", base.get("direction"))
        args.setdefault("dv_mps", base.get("dv_mps"))
    return args


# --------------------------------------------------------------------------- LLM backend (llama-cpp, JSON grammar)

TOOL_SCHEMA = {"type": "object", "properties": {
    "tool": {"enum": sorted(TOOLS)},
    "args": {"type": "object", "properties": {
        "direction": {"enum": list(DIRECTIONS) + ["R", "T", "N"]}, "dv_mps": {"type": "number"},
        "lead_orbits": {"type": "number"}, "n": {"type": "integer"}}}},
    "required": ["tool", "args"]}
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
STEP_SCHEMA = {"anyOf": [TOOL_SCHEMA, ANSWER_SCHEMA]}  # after the first tool call: another tool, or the answer

SYSTEM_PROMPT = (
    "You are OrbitGuard's operator assistant for satellite collision avoidance. The operator decides; you never "
    "command and you never change a recommendation. You may only use these read-only tools, one per step:\n"
    + "\n".join(f"- {n}: {d}" for n, (_, d) in TOOLS.items())
    + "\nEach reply is ONE JSON object: either {\"tool\": <name>, \"args\": {...}} to call a tool, or "
    "{\"answer\": \"...\"} once you have what you need (at most 3 tool calls; call at least one). In the answer use "
    "ONLY facts from the tool results and copy every number exactly as it appears there; never compute, convert "
    "or invent numbers. If a tool says something is not cached, say so. Maximum 120 words. "
    "lead_orbits counts orbits BEFORE closest approach, so burning one orbit later means one less. For a "
    "variation of the recommended burn, call get_event_facts first to read its direction, dv_mps and lead_orbits."
)


def _shared_llama():
    from .backends import LlamaCppBackend
    path = os.environ.get("LLM_MODEL_PATH")
    if not path:
        raise RuntimeError("the llamacpp agent needs LLM_MODEL_PATH (path to a GGUF file)")
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise RuntimeError("llama_cpp_python is not installed in this environment") from exc
    if LlamaCppBackend._llm is None:  # the same instance the brief uses: never load the model twice
        LlamaCppBackend._llm = Llama(model_path=path, n_ctx=max(4096, int(os.environ.get("LLM_N_CTX", "4096"))),
                                     n_threads=os.cpu_count() or 4, verbose=False)
    return LlamaCppBackend._llm


class LlamaChat:
    name = "llamacpp"

    def chat(self, messages: list[dict], schema: dict) -> str:
        out = _shared_llama().create_chat_completion(
            messages=messages, response_format={"type": "json_object", "schema": schema},
            temperature=0.0, max_tokens=400)
        return out["choices"][0]["message"]["content"].strip()


def _resolve_backend(backend):
    """None for the template path, else an object with ``chat(messages, schema) -> str``."""
    if backend is not None and not isinstance(backend, str):
        return backend
    name = (backend or os.environ.get("LLM_BACKEND") or "template").strip().lower()
    if name == "template":
        return None
    if name == "llamacpp":
        return LlamaChat()
    raise ValueError(f"the ask agent supports backends template and llamacpp, not {name!r}")


def _llm_loop(be, question: str, ctx: Context, calls: list[dict]) -> str:
    """Run the tool loop; returns the model's answer or raises ValueError/RuntimeError (caller falls back)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Question about NORAD {ctx.norad}: {question}"}]
    while True:
        final_only = len(calls) >= MAX_TOOL_CALLS
        # first step must be a tool call (grammar-forced); the last step must be an answer
        raw = be.chat(messages, ANSWER_SCHEMA if final_only else STEP_SCHEMA if calls else TOOL_SCHEMA)
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model output is not JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError("model output is not a JSON object")
        if isinstance(obj.get("answer"), str):
            if not calls:
                raise ValueError("model answered without calling a tool")
            return obj["answer"].strip()
        if final_only:
            raise ValueError(f"model kept calling tools after the {MAX_TOOL_CALLS}-call cap")
        tool = obj.get("tool")
        if tool not in TOOLS:
            raise ValueError(f"model chose an unknown tool {tool!r}")
        args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
        res = run_tool(ctx, tool, args)
        calls.append({"tool": tool, "args": args, "result": res})
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"TOOL RESULT ({tool}): " + json.dumps(res, separators=(",", ":"), default=str)}]


# --------------------------------------------------------------------------- public API

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ask(question: str, norad: int | None = None, backend=None) -> dict:
    """Answer ``question`` about the cached live event for ``norad`` (default: ISS, else the latest analysis)."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a nonempty string")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must be at most {MAX_QUESTION_CHARS} characters")
    if norad is not None and (isinstance(norad, bool) or not isinstance(norad, int)):
        raise ValueError("norad must be an integer or null")
    t0 = time.perf_counter()
    question = question.strip()
    ctx = Context(norad)
    be = _resolve_backend(backend)
    calls: list[dict] = []
    reason: str | None = None
    answer: str | None = None
    used = "template"
    guardian: dict = {"status": "not applicable (deterministic template)"}

    if be is not None:
        try:
            answer = _llm_loop(be, question, ctx, calls)
            used = getattr(be, "name", "llm")
            union = {"tools": [c["result"] for c in calls]}
            bad = check_grounding(answer, union)
            if bad:
                reason, answer = f"ungrounded numbers {bad}", None
            else:
                from .guardian import check_groundedness
                guardian = check_groundedness(json.dumps(union, separators=(",", ":"), default=str), answer)
                if guardian.get("flagged"):
                    reason, answer = f"Granite Guardian flagged the answer as not grounded (p_risk={guardian.get('p_risk')})", None
        except Exception as exc:  # noqa: BLE001 - any LLM failure degrades to the deterministic answer, recorded
            reason, answer = f"{type(exc).__name__}: {exc}", None
        if answer is None:
            used = "template"
    if answer is None:
        if not calls:
            calls = [{"tool": t, "args": a, "result": run_tool(ctx, t, a)} for t, a in route(question, ctx)]
        answer = render_answer(calls)

    union = {"tools": [c["result"] for c in calls]}
    grounded = not check_grounding(answer, union)
    result = {"answer": answer, "backend": used, "norad": ctx.norad,
              "tool_calls": [{"tool": c["tool"], "args": c["args"], "result_summary": _summary(c["tool"], c["result"])}
                             for c in calls],
              "grounded": grounded, "guardian": guardian, "fallback_reason": reason,
              "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    from orbitguard.live import _audit
    # No dedicated "ask" kind exists in the audit chain; asks are filed under "brief" with payload type "ask".
    _audit("brief", {"type": "ask", "norad": ctx.norad, "question": question, "backend": used,
                     "tools": [c["tool"] for c in calls], "grounded": grounded,
                     "guardian_flagged": guardian.get("flagged"), "fallback_reason": reason,
                     "answer_sha256": _sha(answer)})
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question")
    ap.add_argument("--norad", type=int, default=None)
    ap.add_argument("--backend", default=None, help="template | llamacpp (default: $LLM_BACKEND)")
    a = ap.parse_args(argv)
    r = ask(a.question, a.norad, a.backend)
    print(r["answer"])
    print()
    print(f"[backend: {r['backend']} | grounded: {r['grounded']} | guardian: {r['guardian'].get('status')}"
          f"{' flagged=' + str(r['guardian'].get('flagged')) if 'flagged' in r['guardian'] else ''} | "
          f"fallback: {r['fallback_reason'] or 'none'} | {r['latency_ms']} ms]")
    for c in r["tool_calls"]:
        print(f"  tool {c['tool']} {json.dumps(c['args'])} -> {c['result_summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
