"""Live-catalogue API: real CelesTrak conjunctions, super-spreader network, harm survey, grounded brief, audit trail.

Heavy work (catalogue screening, consequence, network sweep, an LLM brief) runs in background threads; the
console polls ``/api/live/status``. Each thread may start its own spawn-safe process pool. Results are cached as
JSON under ``DATA_DIR/out`` (default ``artifacts/live/out``) so the console renders instantly after a run.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import Path

from flask import Blueprint, jsonify, request

ISS_NORAD = 25544
DEFAULT_CDM_EVENT = int(os.environ.get("DEFAULT_CDM_EVENT", "8"))  # ESA test event shown as the decision example
OPERATOR_CHOICES = ("accept", "reject", "defer")


class Jobs:
    """Tiny background-job registry: one thread per key, polled through ``snapshot``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def start(self, key: str, fn: Callable[[], object], label: str = "") -> bool:
        """Start ``fn`` unless a job with the same key is already running. Returns True if started."""
        with self._lock:
            cur = self._jobs.get(key)
            if cur and cur["state"] == "running":
                return False
            self._jobs[key] = {"key": key, "label": label or key, "state": "running", "started": time.time(),
                               "finished": None, "error": None}

        def runner() -> None:
            try:
                fn()
                state, err = "done", None
            except Exception as exc:  # noqa: BLE001 - surfaced to the console through /api/live/status
                traceback.print_exc()
                state, err = "error", f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._jobs[key].update(state=state, error=err, finished=time.time())

        threading.Thread(target=runner, name=f"job-{key}", daemon=True).start()
        return True

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            jobs = {k: dict(v, elapsed_s=round((v["finished"] or now) - v["started"], 1)) for k, v in self._jobs.items()}
        return {"running": any(j["state"] == "running" for j in jobs.values()), "jobs": jobs}


# --------------------------------------------------------------------------- platform evidence

def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def platform_info() -> dict:
    """What the judges need to see: s390x, big-endian, machine type, NNPA, accelerated SGP4, container, LLM."""
    try:
        from sgp4.api import accelerated
    except ImportError:
        accelerated = None
    cpuinfo = _read("/proc/cpuinfo")
    machine_type = next((ln.split(":", 1)[1].strip() for ln in _read("/proc/sysinfo").splitlines()
                         if ln.startswith("Type:")), None)
    model_path = os.environ.get("LLM_MODEL_PATH")
    return {
        "machine": platform.machine(), "byteorder": sys.byteorder, "system": platform.system(),
        "python": platform.python_version(), "cpu_count": os.cpu_count(),
        "is_linuxone": platform.machine() == "s390x", "machine_type": machine_type,
        "nnpa_in_cpuinfo": " nnpa" in cpuinfo or "\tnnpa" in cpuinfo,
        "sgp4_accelerated": accelerated,
        "container": Path("/.dockerenv").exists() or bool(os.environ.get("container") or os.environ.get("IN_DOCKER")),
        "llm_backend": os.environ.get("LLM_BACKEND", "template"),
        "llm_model": Path(model_path).name if model_path else None,
    }


# --------------------------------------------------------------------------- latency recorder

class LatencyRecorder:
    """Thread-safe rolling window of wall-clock samples per stage (milliseconds)."""

    def __init__(self, window: int = 500) -> None:
        self._window = window
        self._lock = threading.Lock()
        self._samples: dict[str, deque] = {}

    def record(self, stage: str, ms) -> None:
        if ms is None or isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms != ms or ms < 0:
            return
        with self._lock:
            self._samples.setdefault(stage, deque(maxlen=self._window)).append(float(ms))

    def summary(self) -> dict:
        import numpy as np
        with self._lock:
            copy = {k: list(v) for k, v in self._samples.items()}
        return {k: {"n": len(v), "p50_ms": float(np.percentile(v, 50)), "p95_ms": float(np.percentile(v, 95)),
                    "last_ms": v[-1]} for k, v in copy.items() if v}


LATENCY = LatencyRecorder()
STAGES = ("forecast", "decision_layer", "snap_second_opinion", "live_screen_total", "live_burn_screening")


def latency_payload() -> dict:
    info = platform_info()
    return {"stages": LATENCY.summary(),
            "platform": {"machine": info["machine"], "hostname": platform.node(), "is_linuxone": info["is_linuxone"],
                         "nnpa": info["nnpa_in_cpuinfo"], "byteorder": info["byteorder"]},
            "window": LATENCY._window}


def record_forecast(forecast: dict | None) -> None:
    """Feed one forecast result (as returned by MLService.forecast) into the recorder."""
    if not isinstance(forecast, dict):
        return
    LATENCY.record("forecast", forecast.get("elapsed_ms"))
    stage = forecast.get("stage_ms") or {}
    LATENCY.record("decision_layer", stage.get("decision"))
    LATENCY.record("snap_second_opinion", stage.get("second_opinion"))


def stage_timings(facts: dict, total_s: float, brief_s: float | None) -> dict:
    """Per-stage wall time of one analyse job, from timings collect_facts already measured plus job-level clocks."""
    t = facts.get("timings_s") or {}
    burns = facts.get("burns") or {}
    find_s, screen_s, cons_s = t.get("find_approach_s"), t.get("screen_s"), t.get("consequence_s")
    known = sum(v for v in (find_s, screen_s, cons_s, brief_s) if isinstance(v, (int, float)))
    stages = [
        {"key": "load_search", "label": "Load catalogue, propagate orbits (SGP4) and find the closest approach", "seconds": find_s},
        {"key": "prepare", "label": "Prepare the screen (burn grid, object ephemerides, baseline risk)",
         "seconds": max(0.0, total_s - known) if known else None},
        {"key": "burn_screen", "label": "Screen burns against every object and score Pc and recommend", "seconds": screen_s},
        {"key": "consequence", "label": "Debris consequence assessment", "seconds": cons_s},
        {"key": "brief", "label": "Write the brief", "seconds": brief_s},
    ]
    stages = [s for s in stages if isinstance(s["seconds"], (int, float))]
    n_b, n_o = burns.get("n_screened"), burns.get("n_objects_screened")
    pairs = n_b * n_o if isinstance(n_b, int) and isinstance(n_o, int) else None
    return {"stages": stages, "total_s": total_s, "n_burns": n_b, "n_objects": n_o, "burn_object_pairs": pairs,
            "pairs_per_s": (pairs / screen_s) if pairs and screen_s else None}


# --------------------------------------------------------------------------- cached results

def _out() -> Path:
    from orbitguard.catalog.catalog import data_dir
    return data_dir() / "out"


def _read_json(p: Path | None):
    return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None


def _latest(pattern: str, directory: Path | None = None) -> Path | None:
    files = sorted((directory or _out()).glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _brief_path(norad: int) -> Path:
    return _out() / f"brief_{norad}.json"


def make_and_cache_brief(facts: dict, backend: str | None = None) -> dict:
    from orbitguard.brief.brief import make_brief_from_facts
    b = make_brief_from_facts(facts, backend)
    d = {"text": b.text, "backend_used": b.backend_used, "grounded": b.grounded, "issues": b.issues, "guardian": b.guardian,
         "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "facts_generated_utc": facts.get("generated_utc")}
    p = _brief_path(facts["event"]["primary"]["norad"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")
    return d


def _decision_ready() -> bool:
    from orbitguard.decision.decision import DECISION_PATH
    from orbitguard.decision.train import DATA
    return DECISION_PATH.exists() and (DATA / "test_data.csv").exists()


def _sha(obj) -> str:
    from orbitguard.audit.log import canonical
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def _audit(kind: str, payload: dict) -> dict | None:
    try:  # the audit trail must never break the console
        from orbitguard.audit.log import log_event
        return log_event(kind, payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[audit log failed: {exc}]", file=sys.stderr)
        return None


def network_summary(top: int = 25) -> dict | None:
    net = _read_json(_latest("network_*.json"))
    if net is None:
        return None
    keep = ("rank", "norad", "name", "type", "degree", "score", "mass_kg", "perigee_km", "apogee_km",
            "inclination_deg", "component_size")
    return {"generated_utc": net.get("generated_utc"), "summary": net["summary"], "params": net["params"],
            "timings": net.get("timings"), "nodes": [{k: n.get(k) for k in keep} for n in net["nodes"][:top]],
            "n_nodes_listed": len(net["nodes"])}


def survey_rows() -> list[dict]:
    p = _latest("consequence_survey*.csv")
    if p is None:
        return []
    import pandas as pd
    df = pd.read_csv(p)
    keep = [c for c in ("primary", "norad", "threat", "miss_km", "pc", "harm", "rank_pc", "rank_harm") if c in df]
    return json.loads(df[keep].to_json(orient="records"))


def platform_evidence() -> dict:
    """Measured artefacts for the Validation page; anything not yet run is reported as missing."""
    from orbitguard.nnpa.report import OUT as NNPA_OUT
    speed = _read_json(_latest("speedup_*.json"))
    nnpa = _read_json(_latest("nnpa_bench_*.json", NNPA_OUT)) if NNPA_OUT.exists() else None
    if nnpa:
        nnpa = {k: nnpa.get(k) for k in ("host", "machine", "sysinfo_type", "tf_version", "ibm_zdnn_plugin_version",
                                          "nnpa_available", "table", "max_abs_diff_prob", "cpu_count")}
    net = network_summary(0)
    breakup = _read_json(_out() / "validation.json")
    return {"catalogue_speedup": speed or {"status": "missing"}, "nnpa": nnpa or {"status": "missing"},
            "network": ({k: net[k] for k in ("generated_utc", "summary", "params", "timings")} if net
                        else {"status": "missing"}),
            "breakup_validation": breakup or {"status": "missing"}, "platform": platform_info()}


# --------------------------------------------------------------------------- blueprint

def create_blueprint() -> Blueprint:
    bp = Blueprint("live", __name__)
    jobs = Jobs()

    def body() -> dict:
        value = request.get_json(silent=True)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def analyse_job(norad: int, target_km: float) -> Callable[[], None]:
        def fn() -> None:
            from orbitguard.brief.facts import collect_facts, save_facts
            t_job = time.perf_counter()
            facts = collect_facts(norad, cdm_event=DEFAULT_CDM_EVENT if _decision_ready() else None,
                                  target_km=target_km)
            save_facts(facts)
            collected_s = time.perf_counter() - t_job
            pol = facts["burns"].get("policies") or {}
            _audit("screen", {"primary_norad": norad, "threat_norad": facts["event"]["threat"]["norad"],
                              "tca_utc": facts["event"]["tca_utc"], "status": pol.get("status"),
                              "recommended": (pol.get("orbitguard") or {}).get("burn_id"),
                              "pc_threshold": pol.get("pc_threshold"), "facts_sha256": _sha(facts)})
            brief_s = None
            if os.environ.get("LLM_BACKEND", "template").lower() == "template":
                t_brief = time.perf_counter()
                make_and_cache_brief(facts)
                brief_s = time.perf_counter() - t_brief
            facts["stage_timings"] = stage_timings(facts, collected_s + (brief_s or 0.0), brief_s)
            save_facts(facts)
            LATENCY.record("live_screen_total", facts["stage_timings"]["total_s"] * 1000)
            LATENCY.record("live_burn_screening", (facts.get("timings_s") or {}).get("screen_s", float("nan")) * 1000)
        return fn

    @bp.get("/api/latency")
    def api_latency():
        return jsonify(latency_payload())

    @bp.get("/api/platform")
    def api_platform():
        return jsonify(platform_info())

    @bp.get("/api/live/status")
    def status():
        return jsonify(jobs.snapshot())

    @bp.get("/api/live/events")
    def events():
        out = []
        for p in sorted(_out().glob("facts_*.json")):
            f = _read_json(p)
            if f:
                out.append({"norad": f["event"]["primary"]["norad"], "name": f["event"]["primary"]["name"],
                            "threat": f["event"]["threat"]["name"], "tca_utc": f["event"]["tca_utc"],
                            "status": (f["burns"].get("policies") or {}).get("status"),
                            "generated_utc": f.get("generated_utc")})
        if not any(e["norad"] == ISS_NORAD for e in out):
            out.insert(0, {"norad": ISS_NORAD, "name": "ISS (ZARYA)", "status": None, "generated_utc": None})
        return jsonify({"events": out, "survey": survey_rows()})

    @bp.post("/api/live/analyse")
    def analyse():
        payload = body()
        norad = payload.get("norad", ISS_NORAD)
        target_km = payload.get("target_km", 10.0)
        if isinstance(norad, bool) or not isinstance(norad, int) or not 0 < norad < 10_000_000:
            raise ValueError("norad must be a positive integer NORAD catalogue number")
        if isinstance(target_km, bool) or not isinstance(target_km, (int, float)) or not 0 < target_km <= 100:
            raise ValueError("target_km must be a number in (0, 100]")
        started = jobs.start(f"analyse:{norad}", analyse_job(norad, float(target_km)),
                             f"screening NORAD {norad} against the catalogue")
        return jsonify({"started": started, "key": f"analyse:{norad}", "poll": "/api/live/status"}), 202

    llm_lock = threading.Lock()
    llm_keys: set[str] = set()  # jobs that hold the single llama model (8 GB RAM: never load a second one)
    mem_results: dict[str, dict] = {}  # finished asks that are deliberately not cached on disk (LLM timeouts)

    def llm_running() -> str | None:
        running = {k for k, j in jobs.snapshot()["jobs"].items() if j["state"] == "running"}
        with llm_lock:
            llm_keys.intersection_update(running)
            return next(iter(llm_keys), None)

    def ask_target(payload: dict) -> tuple[str, int, str, str, str]:
        """Validate and return (question, norad, job key, cache file name, facts sha256). 503 if never analysed."""
        from orbitguard.brief.agent import MAX_QUESTION_CHARS, Context
        question, norad = payload.get("question"), payload.get("norad")
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
            raise ValueError(f"question must be a nonempty string of at most {MAX_QUESTION_CHARS} characters")
        if norad is not None and (isinstance(norad, bool) or not isinstance(norad, int) or not 0 < norad < 10_000_000):
            raise ValueError("norad must be a positive integer NORAD catalogue number or null")
        ctx = Context(norad)
        digest = hashlib.sha1(" ".join(question.lower().split()).encode("utf-8")).hexdigest()[:16]
        return question.strip(), ctx.norad, f"ask:{ctx.norad}:{digest}", f"ask_{ctx.norad}_{digest}.json", _sha(ctx.facts)

    def ask_poll(norad: int, question: str) -> str:
        from urllib.parse import quote
        return f"/api/live/ask?norad={norad}&question={quote(question)}"

    def ask_answer(key: str, fname: str, fsha: str, use_mem: bool) -> dict | None:
        hit = mem_results.get(key) if use_mem else None
        if not (hit and hit.get("facts_sha256") == fsha):
            hit = _read_json(_out() / fname)
        return hit if hit and hit.get("facts_sha256") == fsha else None

    @bp.route("/api/live/ask", methods=["GET", "POST"])
    def ask_route():
        from orbitguard.brief.agent import ask
        post_ = request.method == "POST"
        payload = body() if post_ else {
            "question": request.args.get("question"),
            "norad": int(request.args["norad"]) if request.args.get("norad", "").isdigit() else None}
        question, norad, key, fname, fsha = ask_target(payload)
        backend = os.environ.get("LLM_BACKEND", "template").lower()
        refresh = post_ and payload.get("refresh") is True
        job = jobs.snapshot()["jobs"].get(key)
        if not refresh:
            hit = ask_answer(key, fname, fsha, use_mem=not post_)
            if hit and not (job and job["state"] == "running"):
                # served from disk (or just finished by this process): cached only if no job of ours produced it
                fresh = bool(job) and not post_
                return jsonify({"status": "done", "key": key, **hit, "cached": not fresh})
        if not post_:
            if job and job["state"] == "running":
                return jsonify({"status": "running", "key": key, "backend": backend, "elapsed_s": job["elapsed_s"],
                                "poll": ask_poll(norad, question)})
            if job and job["state"] == "error":
                return jsonify({"status": "error", "key": key, "error": job["error"]})
            return jsonify({"status": "none", "key": key, "message": "no answer yet; POST /api/live/ask to start one"})

        use_llm = backend != "template"
        if use_llm:
            other = llm_running()
            if other and other != key:
                return jsonify({"status": "busy", "started": False, "key": key, "busy_with": other,
                                "message": "Granite is busy with another LLM job (a brief or another question). "
                                           "Only one runs at a time on this VM; try again when it finishes."}), 202

        def run() -> None:
            t0 = time.time()
            try:
                res = ask(question, norad, timeout_s=float(os.environ.get("ASK_TIMEOUT_S", "600")))
                res.update(facts_sha256=fsha, question=question, total_s=round(time.time() - t0, 1),
                           generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                path = _out() / fname
                if str(res.get("fallback_reason") or "").startswith("LLM timed out"):
                    mem_results[key] = res  # shown to this poll, but a later identical question tries Granite again
                    path.unlink(missing_ok=True)
                else:
                    mem_results.pop(key, None)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(res), encoding="utf-8")
            finally:
                with llm_lock:
                    llm_keys.discard(key)

        mem_results.pop(key, None) if refresh else None
        with llm_lock:
            if use_llm:
                llm_keys.add(key)
            started = jobs.start(key, run, f"{backend} answer for NORAD {norad}")
            if use_llm and not started:
                llm_keys.discard(key)
        return jsonify({"status": "running", "started": started, "key": key, "backend": backend,
                        "poll": ask_poll(norad, question)}), 202

    @bp.get("/api/live/facts/<int:norad>")
    def facts(norad: int):
        from orbitguard.brief.facts import load_cached_facts
        f = load_cached_facts(norad)
        if f is None:
            raise FileNotFoundError(f"no analysis for NORAD {norad}; POST /api/live/analyse first")
        return jsonify(f)

    def debris_job(norad: int, facts: dict, path: Path) -> Callable[[], None]:
        def fn() -> None:
            from datetime import datetime
            from orbitguard.catalog.catalog import load_catalog
            from orbitguard.catalog.parallel import default_workers
            from orbitguard.consequence.event import Params
            from orbitguard.consequence.viz import debris_payload
            records = load_catalog()
            by_id = {r.norad: r for r in records}
            ev = facts["event"]
            for who in ("primary", "threat"):
                if ev[who]["norad"] not in by_id:
                    raise ValueError(f"{who} NORAD {ev[who]['norad']} is no longer in the catalogue")
            out = debris_payload(by_id[ev["primary"]["norad"]], by_id[ev["threat"]["norad"]],
                                 datetime.fromisoformat(ev["tca_utc"]), ev["miss_km"], records, Params(),
                                 workers=default_workers())
            out["facts_sha256"] = _sha(facts)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        return fn

    @bp.get("/api/live/debris")
    def debris():
        """Simulated fragment cloud for the cached analysis: 200 payload, or 202 while it is computed (poll this URL)."""
        from orbitguard.brief.facts import load_cached_facts
        raw = request.args.get("norad", str(ISS_NORAD))
        if not raw.isdigit() or not 0 < int(raw) < 10_000_000:
            raise ValueError("norad must be a positive integer NORAD catalogue number")
        norad = int(raw)
        f = load_cached_facts(norad)
        if f is None:
            return jsonify({"error": {"code": "no_analysis",
                                      "message": f"no analysis for NORAD {norad}; POST /api/live/analyse first"}}), 404
        path = _out() / f"debris_{norad}_{_sha(f)[:16]}.json"
        if path.exists():
            return jsonify(_read_json(path))
        key = f"debris:{norad}"
        job = jobs.snapshot()["jobs"].get(key)
        if job and job["state"] == "error":
            err = job["error"]
            jobs.start(key, debris_job(norad, f, path), f"debris cloud for NORAD {norad}")  # retry on next poll
            return jsonify({"error": {"code": "debris_failed", "message": err}}), 500
        started = jobs.start(key, debris_job(norad, f, path), f"debris cloud for NORAD {norad}")
        return jsonify({"status": "running", "started": started, "key": key,
                        "poll": f"/api/live/debris?norad={norad}"}), 202

    @bp.route("/api/live/brief/<int:norad>", methods=["GET", "POST"])
    def brief(norad: int):
        from orbitguard.brief.facts import load_cached_facts
        f = load_cached_facts(norad)
        if f is None:
            raise FileNotFoundError(f"no analysis for NORAD {norad}")
        cached = _read_json(_brief_path(norad))
        fresh = cached is not None and cached.get("facts_generated_utc") == f.get("generated_utc")
        if request.method == "GET" and fresh:
            return jsonify(cached)
        backend = os.environ.get("LLM_BACKEND", "template").lower()
        if backend == "template" and request.method == "GET":
            return jsonify(make_and_cache_brief(f))
        # An on-box LLM brief takes seconds to minutes: generate it in the background.
        if backend != "template":
            other = llm_running()
            if other and other != f"brief:{norad}":
                return jsonify({"status": "busy", "started": False, "backend": backend, "previous": cached,
                                "busy_with": other, "poll": "/api/live/status",
                                "message": "Granite is busy answering a question; try again when it finishes."}), 202

        def run_brief() -> None:
            try:
                make_and_cache_brief(f)
            finally:
                with llm_lock:
                    llm_keys.discard(f"brief:{norad}")
        with llm_lock:
            if backend != "template":
                llm_keys.add(f"brief:{norad}")
            started = jobs.start(f"brief:{norad}", run_brief, f"{backend} brief for NORAD {norad}")
            if backend != "template" and not started:
                llm_keys.discard(f"brief:{norad}")
        return jsonify({"status": "computing", "started": started, "backend": backend, "previous": cached,
                        "poll": "/api/live/status"}), 202

    @bp.route("/api/live/network", methods=["GET", "POST"])
    def network():
        if request.method == "POST":
            def run() -> None:
                from orbitguard.network.run import run_network
                run_network(verbose=False)
            started = jobs.start("network", run, "catalogue-wide close-approach network (24 h)")
            return jsonify({"started": started, "poll": "/api/live/status"}), 202
        net = network_summary()
        if net is None:
            raise FileNotFoundError("network sweep has not run; POST /api/live/network")
        return jsonify(net)

    @bp.route("/api/live/survey", methods=["GET", "POST"])
    def survey():
        if request.method == "POST":
            def run() -> None:
                from orbitguard.consequence.run import main as survey_main
                survey_main(["--survey", "20", "--seed", "0"])
            started = jobs.start("survey", run, "Pc vs expected-harm survey of 20 events")
            return jsonify({"started": started, "poll": "/api/live/status"}), 202
        return jsonify({"rows": survey_rows()})

    @bp.get("/api/audit")
    def audit():
        from orbitguard.audit.log import DEFAULT_PATH, tail, verify_log
        ok, bad = verify_log()
        recent = tail(int(request.args.get("n", 20)))
        return jsonify({"path": DEFAULT_PATH.name, "intact": ok, "first_bad_seq": bad,
                        "head": ({k: recent[0][k] for k in ("seq", "utc", "kind", "record_hash")} if recent else None),
                        "recent": [{k: r.get(k) for k in ("seq", "utc", "kind", "payload", "record_hash")}
                                   for r in recent]})

    @bp.post("/api/audit/operator")
    def operator():
        payload = body()
        choice, context = payload.get("choice"), payload.get("context")
        if choice not in OPERATOR_CHOICES:
            raise ValueError(f"choice must be one of {OPERATOR_CHOICES}")
        if context not in ("live", "encounter", "planning"):
            raise ValueError("context must be live, encounter or planning")
        reference = payload.get("reference")
        note = payload.get("note", "")
        if not isinstance(reference, (str, int)) or len(str(reference)) > 128:
            raise ValueError("reference must identify the recommendation (at most 128 characters)")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError("note must be a string of at most 500 characters")
        rec = _audit("operator", {"context": context, "reference": str(reference), "choice": choice, "note": note,
                                  "recommendation": payload.get("recommendation")})
        if rec is None:
            raise RuntimeError("audit log unavailable")
        return jsonify({k: rec[k] for k in ("seq", "utc", "kind", "record_hash")}), 201

    @bp.get("/api/evidence/platform")
    def evidence_platform():
        return jsonify(platform_evidence())

    return bp
