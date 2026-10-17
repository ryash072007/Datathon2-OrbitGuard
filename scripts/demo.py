"""One-command demo prep for the combined console: python scripts/demo.py [--quick] [--llm] [--no-serve]

Stages (idempotent; downloads and frozen models are reused when present):
  ESA data -> forecast model (train + held-out evaluate) -> decision layer (fit + sealed eval) -> physics validation
  -> synthetic planner benchmark -> live ISS analysis with brief -> Pc-vs-harm survey -> network sweep -> serve.
--quick skips the planner benchmark, survey and network sweep. Timings go to
artifacts/live/out/demo_timings_<host>.json before the server starts.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ML = ROOT / "artifacts" / "ml"
CLI = [sys.executable, "-m", "orbitguard"]


def run_stage(name: str, args: list[str], env: dict[str, str]) -> dict:
    print(f"\n=== {name}: orbitguard {' '.join(args)}", flush=True)
    t0 = time.perf_counter()
    rc = subprocess.call(CLI + args, cwd=ROOT, env=env)
    wall = time.perf_counter() - t0
    status = "ok" if rc == 0 else f"FAILED(rc={rc})"
    print(f"=== {name}: {status} in {wall:.1f}s", flush=True)
    return {"stage": name, "status": status, "wall_s": round(wall, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip the planner benchmark, survey and network sweep")
    ap.add_argument("--llm", action="store_true",
                    help="write the brief with Granite via llama.cpp (needs LLM_MODEL_PATH, see docs/vm_runbook.md)")
    ap.add_argument("--no-serve", action="store_true", help="prepare everything but do not start the console")
    ap.add_argument("--target-km", type=float, default=10.0)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = ap.parse_args()

    env = dict(os.environ, PYTHONUNBUFFERED="1", ORBITGUARD_ROOT=str(ROOT))
    if args.llm:
        env["LLM_BACKEND"] = "llamacpp"
        env.setdefault("LLM_MODEL_PATH", str(ROOT / "artifacts" / "llm" / "granite-3.3-2b-instruct-q8_0-be.gguf"))
        if not Path(env["LLM_MODEL_PATH"]).exists():
            print(f"warning: LLM model not found at {env['LLM_MODEL_PATH']}; the brief falls back to the template")

    stages: list[tuple[str, list[str]]] = []
    if not (ML / "data" / "train_data.csv").exists():
        stages += [("fetch_data", ["fetch-data"]), ("prepare_data", ["prepare-data"])]
    if not (ML / "evidence.json").exists():
        stages += [("train", ["train"]), ("evaluate", ["evaluate"])]
    if not (ML / "decision_evidence.json").exists():
        stages += [("decision_fit", ["decision-fit"]), ("decision_eval", ["decision-eval"])]
    stages.append(("validate_physics", ["validate-physics"]))
    if not args.quick:
        stages.append(("benchmark_planner", ["benchmark-planner", "--count", "50", "--runtime-repetitions", "5"]))
    stages.append(("live_iss", ["brief", "--primary", "25544", "--cdm-event", "8", "--target-km", str(args.target_km)]))
    if not args.quick:
        stages.append(("survey20", ["consequence", "--survey", "20", "--seed", "0"]))
        stages.append(("network_24h", ["network", "--hours", "24"]))

    results, t_all = [], time.perf_counter()
    for name, cmd in stages:
        r = run_stage(name, cmd, env)
        results.append(r)
        if r["status"] != "ok":
            break

    host = platform.node() or "host"
    out = ROOT / "artifacts" / "live" / "out"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"demo_timings_{host}.json"
    summary = {"host": host, "machine": platform.machine(), "byteorder": sys.byteorder,
               "cpus": os.cpu_count(), "quick": args.quick, "llm": args.llm,
               "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "total_s": round(time.perf_counter() - t_all, 2), "stages": results}
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nTiming summary")
    for r in results:
        print(f"  {r['stage']:<22} {r['status']:<12} {r['wall_s']:8.1f}s")
    print(f"  {'total':<22} {'':<12} {summary['total_s']:8.1f}s\n  written: {path}")
    if any(r["status"] != "ok" for r in results):
        return 1
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("note: the console is not built; run `npm ci && npm run build` in frontend/ (the API still works)")
    if args.no_serve:
        print(f"console not started (--no-serve). Start with: orbitguard serve --port {args.port}")
        return 0
    print(f"\nStarting the console on http://localhost:{args.port}  (Ctrl-C to stop)")
    try:
        return subprocess.call(CLI + ["serve", "--host", "0.0.0.0", "--port", str(args.port), "--root", str(ROOT)],
                               cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
