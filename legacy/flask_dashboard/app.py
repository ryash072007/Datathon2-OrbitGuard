"""Flask dashboard: pick a conjunction, see risk, burns, consequence, network and the grounded brief.

Pages are rendered from cached results in <DATA_DIR>/out. Heavy work (event analysis, network sweep, survey)
runs in background threads started by the "Run" buttons, and the page polls /api/status.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

import pandas as pd
from flask import Flask, Response, abort, jsonify, render_template, request

from orbitguard.brief.brief import make_brief_from_facts
from orbitguard.brief.facts import collect_facts, decision_facts, latest_file, load_cached_facts, save_facts
from orbitguard.catalog.catalog import data_dir

from .charts import bar_chart, globe_svg, markdown_html, network_svg, slope_chart
from .jobs import Jobs

ISS_NORAD = 25544


def platform_info() -> dict:
    return {"machine": platform.machine(), "byteorder": sys.byteorder, "cpu_count": os.cpu_count(),
            "system": platform.system(), "python": platform.python_version(),
            "container": in_container()}


def in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("container")) or bool(os.environ.get("IN_DOCKER"))


def load_speedup() -> dict | None:
    p = latest_file("speedup_*.json")
    if not p:
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    mach = d.get("machine")
    if mach == "s390x":
        d["context"] = "IBM LinuxONE (s390x)"
    elif mach:
        d["context"] = f"{d.get('system', '')} {mach} · {d['host']}".strip()
    else:
        d["context"] = f"host {d['host']} (machine type not recorded)"
    d["linuxone"] = mach == "s390x"
    return d


def audit_head() -> dict | None:
    """Last record of the hash-chained decision log (seq, hash, utc, count), if present."""
    try:
        from orbitguard.audit.log import DEFAULT_PATH
        lines = [ln for ln in DEFAULT_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return None
        last = json.loads(lines[-1])
        return {"seq": last["seq"], "hash": last["record_hash"], "utc": last["utc"], "n": len(lines)}
    except (OSError, ValueError, KeyError, ImportError):
        return None


def out_dir() -> Path:
    return data_dir() / "out"


def load_network() -> dict | None:
    p = latest_file("network_*.json")
    return json.loads(p.read_text(encoding="utf-8")) if p else None


def load_survey() -> list[dict]:
    p = latest_file("consequence_survey*.csv")
    if p is None:
        return []
    df = pd.read_csv(p)
    need = {"primary", "norad", "threat", "rank_pc", "rank_harm"}
    if not need <= set(df.columns):
        return []
    return df.to_dict("records")


def _brief_cache(norad: int) -> Path:
    return out_dir() / f"brief_{norad}.json"


def make_and_cache_brief(facts: dict) -> dict:
    b = make_brief_from_facts(facts)
    d = {"text": b.text, "backend_used": b.backend_used, "grounded": b.grounded, "issues": b.issues}
    p = _brief_cache(facts["event"]["primary"]["norad"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")
    return d


def _globe_path(norad: int) -> Path:
    return out_dir() / f"globe_{norad}.json"


def _replay_path(event_id: int) -> Path:
    return out_dir() / f"replay_{event_id}.json"


def _replay_demo_path() -> Path:
    return out_dir() / "replay_demo.json"


def _read_json(p: Path) -> dict | list | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")


def compute_replay(event_id: int) -> dict:
    from orbitguard.decision.replay import replay
    d = {"event_id": event_id, "split": "test", "steps": replay(event_id)}
    _write_json(_replay_path(event_id), d)
    return d


DEFAULT_DECISION_EVENT = 276  # ESA test event that escalates MONITOR -> ACT in the replay demo


def default_decision() -> dict | None:
    """Decision layer on a default historical ESA event, cached; None if the CDM data or model is missing."""
    p = out_dir() / f"decision_{DEFAULT_DECISION_EVENT}.json"
    cached = _read_json(p)
    if cached is not None:
        return cached
    try:
        d = decision_facts(DEFAULT_DECISION_EVENT)
    except (FileNotFoundError, ValueError, KeyError):
        return None
    _write_json(p, d)
    return d


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # static assets always revalidate (dashboard is edited live)
    jobs = Jobs()
    default_cdm = int(os.environ.get("DEFAULT_CDM_EVENT", "8"))

    def event_job(norad: int):
        def fn() -> None:
            facts = collect_facts(norad, cdm_event=default_cdm)
            save_facts(facts)
            make_and_cache_brief(facts)
        return fn

    def network_job() -> None:
        from orbitguard.network.run import run_network
        run_network(verbose=False)

    def survey_job() -> None:
        from orbitguard.consequence.run import main as survey_main
        survey_main(["--survey", "20", "--seed", "0"])

    def globe_job(norad: int):
        def fn() -> None:
            from orbitguard.consequence.snapshot import cloud_snapshots
            facts = load_cached_facts(norad)
            if facts is None:
                raise RuntimeError(f"no cached analysis for NORAD {norad}")
            cloud_snapshots(facts)
        return fn

    def replay_demo_job() -> None:
        from orbitguard.decision.replay import pick_demo_events
        picks = pick_demo_events()
        for d in picks:
            compute_replay(d["event_id"])
        _write_json(_replay_demo_path(), picks)

    @app.get("/")
    def index():
        survey = load_survey()
        events = [{"norad": ISS_NORAD, "label": "ISS (ZARYA), default"}]
        events += [{"norad": int(r["norad"]), "label": f"{r['primary']} (survey, vs {r['threat']})"}
                   for r in survey if int(r["norad"]) != ISS_NORAD]
        norad = request.args.get("norad", type=int) or ISS_NORAD
        facts = load_cached_facts(norad)
        brief = None
        if facts:
            if os.environ.get("LLM_BACKEND", "template").lower() == "template":
                brief = make_and_cache_brief(facts)
            elif _brief_cache(norad).exists():
                brief = json.loads(_brief_cache(norad).read_text(encoding="utf-8"))
        net = load_network()
        cons = (facts or {}).get("consequence") or {}
        decision = ((facts or {}).get("risk") or {}).get("decision") or default_decision()
        boot = {
            "norad": norad, "have_facts": bool(facts), "event": (facts or {}).get("event"),
            "burns": (facts or {}).get("burns"), "cons": cons or None, "decision": decision,
            "live_pc": ((facts or {}).get("risk") or {}).get("live_pc"),
            "survey": [{k: r[k] for k in ("primary", "norad", "threat", "rank_pc", "rank_harm", "pc", "harm")
                        if k in r} for r in survey],
            "net": ({"summary": net["summary"], "params": net["params"], "timings": net["timings"],
                     "nodes": [{k: n.get(k) for k in ("rank", "norad", "name", "type", "degree", "score",
                                                      "perigee_km", "apogee_km", "inclination_deg")}
                               for n in net["nodes"]],
                     "edges": [[e["a"], e["b"]] for e in net["edges"]]} if net else None),
            "brief": ({k: brief.get(k) for k in ("backend_used", "grounded", "issues")} if brief else None),
            "speedup": load_speedup(), "audit": audit_head(), "platform": platform_info(),
            "llm_backend": os.environ.get("LLM_BACKEND", "template"),
        }
        return render_template(
            "index.html", boot=boot, events=events, norad=norad, facts=facts, brief=brief, platform=platform_info(),
            burns=((facts or {}).get("burns") or {}).get("top", []),
            decision=((facts or {}).get("risk") or {}).get("decision") or default_decision(),
            brief_html=markdown_html(brief["text"]) if brief else "",
            bars=bar_chart(cons.get("exposed_by_constellation") or {}) if cons else "",
            slope=slope_chart(survey, selected=norad), n_survey=len(survey),
            net=net, net_top=(net or {}).get("nodes", [])[:15],
            net_svg=network_svg(net["nodes"], net["edges"]) if net else "",
            llm_backend=os.environ.get("LLM_BACKEND", "template"),
            globe_ready=_globe_path(norad).exists())

    @app.get("/api/status")
    def status():
        snap = jobs.snapshot()
        snap["platform"] = platform_info()
        return jsonify(snap)

    @app.route("/api/event/<int:norad>", methods=["GET", "POST"])
    def api_event(norad: int):
        if request.method == "POST":
            started = jobs.start(f"event:{norad}", event_job(norad), f"analysing NORAD {norad}")
            return jsonify({"started": started}), 202
        facts = load_cached_facts(norad)
        if facts is None:
            return jsonify({"status": "missing", "hint": f"POST /api/event/{norad} to compute"}), 404
        return jsonify(facts)

    @app.post("/api/run/<what>")
    def api_run(what: str):
        fns = {"network": (network_job, "network sweep"), "survey": (survey_job, "survey of 20 events")}
        if what not in fns:
            abort(404)
        started = jobs.start(what, fns[what][0], fns[what][1])
        return jsonify({"started": started}), 202

    @app.get("/api/brief/<int:norad>")
    def api_brief(norad: int):
        facts = load_cached_facts(norad)
        if facts is None:
            return jsonify({"status": "missing"}), 404
        return jsonify(make_and_cache_brief(facts))

    @app.route("/api/globe/<int:norad>", methods=["GET", "POST"])
    def api_globe(norad: int):
        cached = _read_json(_globe_path(norad))
        if request.method == "GET" and cached is not None:
            return jsonify(cached)
        if load_cached_facts(norad) is None:
            return jsonify({"status": "missing", "hint": f"run the analysis for NORAD {norad} first"}), 404
        started = jobs.start(f"globe:{norad}", globe_job(norad), f"3D cloud for NORAD {norad}")
        return jsonify({"status": "computing", "started": started, "poll": "/api/status"}), 202

    @app.get("/api/globe/<int:norad>/fallback.svg")
    def api_globe_svg(norad: int):
        cached = _read_json(_globe_path(norad))
        if cached is None:
            abort(404)
        return Response(globe_svg(cached), mimetype="image/svg+xml")

    @app.get("/api/replay/demo")
    def api_replay_demo():
        picks = _read_json(_replay_demo_path())
        if picks is not None:
            return jsonify(picks)
        started = jobs.start("replay_demo", replay_demo_job, "choosing replay demo events")
        return jsonify({"status": "computing", "started": started, "poll": "/api/status"}), 202

    @app.get("/api/replay/<int:event_id>")
    def api_replay(event_id: int):
        cached = _read_json(_replay_path(event_id))
        if cached is not None:
            return jsonify(cached)
        try:
            return jsonify(compute_replay(event_id))
        except (ValueError, FileNotFoundError) as exc:
            return jsonify({"status": "missing", "error": str(exc)}), 404

    return app
