"""CLI: python -m src.screen.run --primary 25544 --days 3 [--workers N] [--target-km 2] [--benchmark]"""
from __future__ import annotations

import argparse
import json
import math
import os
import socket
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from .burns import burn_grid
from .catalog import data_dir, load_catalog, period_min_from_tle
from .parallel import default_workers
from .screen import find_approach, prepare, run_burns


def _worker_counts(max_w: int) -> list[int]:
    counts, w = [], 1
    while w < max_w:
        counts.append(w)
        w *= 2
    counts.append(max_w)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primary", type=int, default=25544, help="NORAD id of the primary (default ISS)")
    ap.add_argument("--days", type=float, default=3.0, help="search window for the closest approach")
    ap.add_argument("--workers", type=int, default=None, help="default: $WORKERS or os.cpu_count()")
    ap.add_argument("--target-km", type=float, default=2.0, help="required miss distance (TLE error ~1 km)")
    ap.add_argument("--threat", type=int, default=None, help="force the threat NORAD id")
    ap.add_argument("--lam", type=float, default=0.05, help="m/s per unit criticality")
    ap.add_argument("--r-km", type=float, default=5.0, help="conjunction radius")
    ap.add_argument("--benchmark", action="store_true", help="time burn screening for 1,2,4..cpu_count workers")
    ap.add_argument("--refresh", action="store_true", help="force re-download of CelesTrak data")
    args = ap.parse_args(argv)
    workers = args.workers or default_workers()

    timings: dict[str, float] = {}
    t = time.perf_counter()
    records = load_catalog(force=args.refresh)
    timings["load_catalog_s"] = time.perf_counter() - t
    by_id = {r.norad: r for r in records}
    if args.primary not in by_id:
        raise SystemExit(f"primary NORAD {args.primary} not found in the catalogue")
    primary = by_id[args.primary]

    now = datetime.now(timezone.utc).replace(microsecond=0)
    t = time.perf_counter()
    period_min = period_min_from_tle(primary.line2)
    # start late enough that at least the shortest burn lead (0.5 period) still lies in the future
    start = now + timedelta(minutes=0.5 * period_min + 2)
    found = find_approach(primary, records, start, args.days, only_norad=args.threat)
    timings["find_approach_s"] = time.perf_counter() - t
    tca = found["tca"].replace(microsecond=0)
    threat = found["record"]
    print(f"Primary {primary.name} ({primary.norad}); {len(records)} catalogue objects")
    print(f"Closest approach in next {args.days:g} d: {threat.name} ({threat.norad}) at {tca.isoformat()} "
          f"miss {found['miss_km']:.2f} km ({found['n_under_r']} window(s) under {found['r_km']:g} km)")

    burns = burn_grid(tca, period_min, earliest=now + timedelta(seconds=60))
    ctx = prepare(primary.tle, records, tca, burns, target_km=args.target_km, lam=args.lam,
                  r_km=args.r_km, threat_norad=threat.norad)
    timings.update({k: v for k, v in ctx.timings.items()})
    print(f"Screening {len(burns)} burns vs {len(ctx.tles)} objects (baseline miss {ctx.baseline_miss_km:.2f} km, "
          f"{len(ctx.base_close)} baseline object(s) within {args.r_km:g} km)")

    df = run_burns(ctx, burns, workers)
    timings["burns_s"] = df.attrs["timings"]["burns_s"]
    timings["workers"] = workers
    timings["total_s"] = sum(v for k, v in timings.items() if k.endswith("_s") and k != "total_s")

    out_dir = data_dir() / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"screen_{primary.norad}_{now.strftime('%Y%m%dT%H%M%SZ')}"
    df.to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8")

    burn_df = df[df["direction"] != "none"]
    top = burn_df.head(10)
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.3f}".format):
        print(top.drop(columns=["burn_time_utc", "analytic_seed"]).to_string())
    best = burn_df.iloc[0]
    needed = ctx.baseline_miss_km < args.target_km
    best_by_dir = {d: g.iloc[0]["burn_id"] for d, g in burn_df.groupby("direction", sort=False)}
    feas = burn_df[burn_df["feasible"]]
    along_won = bool(best["analytic_seed"])
    print(f"Manoeuvre needed at target {args.target_km:g} km: {needed}. Best burn: {best['burn_id']} "
          f"(dv {best['dv_mps']} m/s, miss {best['miss_km_threat']:.2f} km, new conj {best['new_conjunctions']}). "
          f"Along-track won: {along_won}. Feasible burns: {len(feas)}/{len(burn_df)}.")

    summary = {
        "primary": {"name": primary.name, "norad": primary.norad},
        "threat": {"name": threat.name, "norad": threat.norad},
        "tca_utc": tca.isoformat(), "baseline_miss_km": ctx.baseline_miss_km,
        "closest_found_km": found["miss_km"], "approach_under_50km": found["miss_km"] < 50.0,
        "target_km": args.target_km, "manoeuvre_needed": needed,
        "best_burn": {k: (v.item() if hasattr(v, "item") else v) for k, v in best.to_dict().items()},
        "best_burn_by_direction": best_by_dir, "along_track_won": along_won,
        "n_burns": len(burns), "n_objects_screened": len(ctx.tles), "timings": timings,
        "csv": f"{stem}.csv",
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out_dir / (stem + '.csv')} and .json; timings: "
          + ", ".join(f"{k}={v:.2f}" for k, v in timings.items() if isinstance(v, float)))

    if args.benchmark:
        max_w = args.workers or os.cpu_count() or 1
        rows, base_t = [], None
        for w in _worker_counts(max_w):
            t = time.perf_counter()
            run_burns(ctx, burns, w)
            wall = time.perf_counter() - t
            base_t = base_t or wall
            rows.append({"workers": w, "wall_s": round(wall, 3), "speedup": round(base_t / wall, 2)})
            print(f"benchmark workers={w:3d} wall={wall:7.2f}s speedup={base_t / wall:5.2f}x")
        host = socket.gethostname()
        (out_dir / f"speedup_{host}.json").write_text(
            json.dumps({"host": host, "cpu_count": os.cpu_count(), "n_burns": len(burns),
                        "n_objects": len(ctx.tles), "results": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
