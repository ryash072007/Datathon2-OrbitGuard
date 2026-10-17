"""One-command demo prep: python scripts/demo.py [--quick] [--llm] [--no-serve]

Stages (idempotent; cached downloads and an existing decision model are reused):
  get_data, decision fit, screener (ISS, 10 km), consequence survey 20, network sweep 24 h,
  brief facts, dashboard. --quick skips the survey and the network sweep.
Timings go to data/out/demo_timings_<host>.json (written before the server starts).
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
PY = sys.executable
MODEL = ROOT / "models" / "decision.joblib"


def run_stage(name: str, cmd: list[str], env: dict[str, str]) -> dict:
    print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
    t0 = time.perf_counter()
    rc = subprocess.call(cmd, cwd=ROOT, env=env)
    wall = time.perf_counter() - t0
    status = "ok" if rc == 0 else f"FAILED(rc={rc})"
    print(f"=== {name}: {status} in {wall:.1f}s", flush=True)
    return {"stage": name, "status": status, "wall_s": round(wall, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip the consequence survey and the network sweep")
    ap.add_argument("--llm", action="store_true",
                    help="write the brief with llama.cpp (needs LLM_MODEL_PATH, see docs/vm_runbook.md)")
    ap.add_argument("--no-serve", action="store_true", help="prepare everything but do not start the dashboard")
    ap.add_argument("--target-km", type=float, default=10.0)
    args = ap.parse_args()

    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if args.llm:
        env["LLM_BACKEND"] = "llamacpp"
        env.setdefault("LLM_MODEL_PATH", str(ROOT / "models" / "llm" / "granite-3.3-2b-instruct-q8_0-be.gguf"))
        if not Path(env["LLM_MODEL_PATH"]).exists():
            print(f"warning: LLM model not found at {env['LLM_MODEL_PATH']}; the brief falls back to the template")
    m = [PY, "-m"]
    stages: list[tuple[str, list[str]]] = [("get_data", [PY, "scripts/get_data.py"])]
    if MODEL.exists():
        print(f"decision fit: skipped, {MODEL.relative_to(ROOT)} exists")
    else:
        stages.append(("decision_fit", m + ["src.risk.decision", "fit"]))
    stages.append(("screen_iss", m + ["src.screen.run", "--primary", "25544", "--target-km", str(args.target_km)]))
    if not args.quick:
        stages.append(("consequence_survey20", m + ["src.consequence.run", "--survey", "20", "--seed", "0"]))
        stages.append(("network_24h", m + ["src.network.run", "--hours", "24"]))
    stages.append(("brief_facts", m + ["src.brief.run", "--primary", "25544", "--target-km", str(args.target_km)]))

    results, t_all = [], time.perf_counter()
    for name, cmd in stages:
        r = run_stage(name, cmd, env)
        results.append(r)
        if r["status"] != "ok":
            break

    host = platform.node() or "host"
    out = ROOT / "data" / "out"
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
    if args.no_serve:
        print("dashboard not started (--no-serve). Start with: python -m src.app.run")
        return 0
    port = env.get("PORT", "8080")
    print(f"\nStarting dashboard on http://localhost:{port}  (Ctrl-C to stop)")
    try:
        return subprocess.call(m + ["src.app.run"], cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
