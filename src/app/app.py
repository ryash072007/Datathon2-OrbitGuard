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
from flask import Flask, abort, jsonify, render_template, request

from src.brief.brief import make_brief_from_facts
from src.brief.facts import collect_facts, latest_file, load_cached_facts, save_facts
from src.screen.catalog import data_dir

from .charts import bar_chart, network_svg, slope_chart
from .jobs import Jobs

ISS_NORAD = 25544


def platform_info() -> dict:
    return {"machine": platform.machine(), "byteorder": sys.byteorder, "cpu_count": os.cpu_count(),
            "system": platform.system(), "python": platform.python_version()}


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


def create_app() -> Flask:
    app = Flask(__name__)
    jobs = Jobs()
    default_cdm = int(os.environ.get("DEFAULT_CDM_EVENT", "8"))

    def event_job(norad: int):
        def fn() -> None:
            facts = collect_facts(norad, cdm_event=default_cdm)
            save_facts(facts)
            make_and_cache_brief(facts)
        return fn

    def network_job() -> None:
        from src.network.run import run_network
        run_network(verbose=False)

    def survey_job() -> None:
        from src.consequence.run import main as survey_main
        survey_main(["--survey", "20", "--seed", "0"])

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
        return render_template(
            "index.html", events=events, norad=norad, facts=facts, brief=brief, platform=platform_info(),
            burns=((facts or {}).get("burns") or {}).get("top", []),
            decision=((facts or {}).get("risk") or {}).get("decision"),
            bars=bar_chart(cons.get("exposed_by_constellation") or {}) if cons else "",
            slope=slope_chart(survey, selected=norad), n_survey=len(survey),
            net=net, net_top=(net or {}).get("nodes", [])[:15],
            net_svg=network_svg(net["nodes"], net["edges"]) if net else "",
            llm_backend=os.environ.get("LLM_BACKEND", "template"))

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

    return app
