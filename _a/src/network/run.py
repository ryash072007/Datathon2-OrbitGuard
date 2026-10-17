"""CLI: python -m src.network.run --hours 24 [--step-s 10] [--r-km 10] [--workers N]"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from src.screen.catalog import data_dir, load_catalog
from src.screen.parallel import default_workers

from .graph import build_network, select_nodes, sweep


def run_network(hours: float = 24.0, step_s: float = 10.0, r_km: float = 10.0, top: int = 300,
                workers: int | None = None, refresh: bool = False, verbose: bool = True):
    """Run the sweep, write data/out/network_<utc>.json, return (path, payload)."""
    workers = workers or default_workers()
    tim: dict[str, float] = {}
    t = time.perf_counter()
    records = select_nodes(load_catalog(force=refresh))
    tim["load_s"] = time.perf_counter() - t
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    if verbose:
        n_deb = sum(1 for r in records if r.group != "active")
        print(f"{len(records)} nodes ({len(records) - n_deb} active LEO payloads, {n_deb} debris-group objects); "
              f"{hours:g} h at {step_s:g} s, pairs within {r_km:g} km, {workers} worker(s)")
    sw = sweep(records, t0, hours, step_s, r_km, workers)
    tim.update(sw["timings"])
    t = time.perf_counter()
    net = build_network(records, sw, top)
    tim["score_s"] = time.perf_counter() - t
    out = data_dir() / "out"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"network_{t0.strftime('%Y%m%dT%H%M%SZ')}.json"
    payload = {"generated_utc": t0.isoformat(), "params": {"hours": hours, "step_s": step_s, "r_km": r_km,
                                                           "top": top}, "timings": tim, **net}
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path, payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--step-s", type=float, default=10.0)
    ap.add_argument("--r-km", type=float, default=10.0)
    ap.add_argument("--top", type=int, default=300, help="nodes kept in the output file")
    ap.add_argument("--workers", type=int, default=None, help="default: $WORKERS or os.cpu_count()")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    path, payload = run_network(args.hours, args.step_s, args.r_km, args.top, args.workers, args.refresh)
    s = payload["summary"]
    print(f"{s['n_edges']} edges, {s['n_components']} components (largest {s['largest_component']}), "
          f"{s['n_isolated']} isolated nodes")
    print(f"{'#':>3} {'name':<28} {'type':<12} {'degree':>6} {'score':>7}")
    for nd in payload["nodes"][:15]:
        print(f"{nd['rank']:>3} {nd['name'][:28]:<28} {nd['type']:<12} {nd['degree']:>6} {nd['score']:>7.4f}")
    for ty, lst in payload["top_by_type"].items():
        print(f"top {ty}: " + "; ".join(f"{x['name'][:22]} (deg {x['degree']})" for x in lst[:3]))
    print("timings (s): " + ", ".join(f"{k}={v:.2f}" for k, v in payload["timings"].items()))
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
