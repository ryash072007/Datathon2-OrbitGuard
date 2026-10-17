"""CLI: python -m orbitguard.consequence.run --primary 25544 [--threat ID]   |   --survey 20 --seed 0"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from orbitguard.catalog.catalog import data_dir, load_catalog, period_min_from_tle
from orbitguard.catalog.parallel import default_workers, map_tasks
from orbitguard.catalog.screen import find_approach

from .event import LEO_PERIGEE_KM, Params, assess, survey_task
from .objects import ASSUMPTIONS, ISS_NORAD, PAYLOAD, object_type


def _print_event(res: dict) -> None:
    a, b = res["primary"], res["threat"]
    print(f"Event: {a['name']} ({a['norad']}, {a['type']}, {a['mass_kg']:g} kg) x {b['name']} ({b['norad']}, "
          f"{b['type']}, {b['mass_kg']:g} kg) at {res['tca_utc']}, miss {res['miss_km']:.2f} km, "
          f"v_rel {res['v_rel_kms']:.1f} km/s, altitude ~{res['parent_alt_km']:.0f} km")
    print(f"Collision type: {'CATASTROPHIC' if res['catastrophic'] else 'non-catastrophic'}; ejected mass "
          f"{res['ejected_mass_kg']:.0f} kg")
    print(f"Fragments >=10 cm: true {res['fragments_true']:.0f}, sampled {res['fragments_sampled']} "
          f"(weight {res['fragment_weight']:.2f}); re-entered (perigee<150 km) {100 * res['reentered_fraction']:.1f}%, "
          f"unbound {100 * res['unbound_fraction']:.1f}%")
    if res["alt_day1_p10_p50_p90_km"]:
        lo, mid, hi = res["alt_day1_p10_p50_p90_km"]
        print(f"Fragment altitude at day 0.5 (p10/p50/p90): {lo:.0f}/{mid:.0f}/{hi:.0f} km; "
              f"{100 * res['frac_within_100km_of_parent_alt_day1']:.0f}% within 100 km of the parent altitude")
    print(f"Pc (sigma {res['params']['sigma_km']:g} km, HBR {res['params']['hbr_m']:g} m): {res['pc']:.3e}")
    print(f"Satellites put at risk (>=1 expected encounter within {res['params']['r_km']:g} km over "
          f"{res['params']['n_days']} d): {res['n_sats_ge1_encounter']} of {res['n_sats_considered']}; "
          f"any exposure (>0.01): {res['n_sats_any_exposure']}; total expected encounters "
          f"{res['total_expected_encounters']:.1f}")
    print(f"Expected harm = Pc x total expected encounters = {res['expected_harm']:.3e}")
    print("Top affected satellites: " + "; ".join(f"{s['name']} ({s['expected_encounters']:.2f})"
                                                  for s in res["top_satellites"]))
    print("Exposed by constellation: " + ", ".join(f"{k}={v}" for k, v in res["exposed_by_constellation"].items()))
    print("Stage timings (s): " + ", ".join(f"{k}={v:.2f}" for k, v in res["timings"].items()))


def _single(args, records, workers: int, params: Params, out_dir, stamp: str) -> None:
    by_id = {r.norad: r for r in records}
    if args.primary not in by_id:
        raise SystemExit(f"primary NORAD {args.primary} not in the catalogue")
    primary = by_id[args.primary]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    t = time.perf_counter()
    found = find_approach(primary, records, now + timedelta(minutes=1), args.days, only_norad=args.threat)
    t_find = time.perf_counter() - t
    tca = found["tca"].replace(microsecond=0)
    res = assess(primary, found["record"], tca, found["miss_km"], records, params, workers)
    res["timings"]["find_approach_s"] = t_find
    res["assumptions"] = ASSUMPTIONS
    _print_event(res)
    print("Mass assumptions (APPROXIMATE): " + json.dumps(ASSUMPTIONS["mass_kg_by_type"]) + " "
          + json.dumps(ASSUMPTIONS["mass_kg_by_name_prefix"]) + " ISS 420000 kg")
    stem = f"consequence_{primary.norad}_{stamp}"
    (out_dir / f"{stem}.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    flat = {k: v for k, v in res.items() if not isinstance(v, (dict, list))}
    pd.DataFrame([flat]).to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8")
    print(f"Wrote {out_dir / (stem + '.csv')} and .json")


def _survey(args, records, workers: int, params: Params, out_dir, stamp: str) -> None:
    rng = np.random.default_rng(args.seed)
    pool = [r for r in records if r.group == "active" and r.perigee_km < LEO_PERIGEE_KM
            and object_type(r) == PAYLOAD and r.norad != ISS_NORAD]
    pool.sort(key=lambda r: r.norad)  # deterministic order independent of catalogue order
    pick = [pool[i] for i in rng.choice(len(pool), size=args.survey - 1, replace=False)]
    iss = next((r for r in records if r.norad == ISS_NORAD), None)
    if iss is not None:
        pick.insert(0, iss)
    tasks = [{"primary": r, "records": records, "params": params, "days": args.days, "index": i}
             for i, r in enumerate(pick)]
    t = time.perf_counter()
    results = map_tasks(survey_task, tasks, workers)
    wall = time.perf_counter() - t
    df = pd.DataFrame([{
        "primary": r["primary"]["name"], "norad": r["primary"]["norad"], "threat": r["threat"]["name"],
        "threat_type": r["threat"]["type"], "tca_utc": r["tca_utc"], "miss_km": r["miss_km"],
        "v_rel_kms": r["v_rel_kms"], "catastrophic": r["catastrophic"], "fragments_true": r["fragments_true"],
        "pc": r["pc"], "n_sats_any_exposure": r["n_sats_any_exposure"], "n_ge1": r["n_sats_ge1_encounter"], "encounters": r["total_expected_encounters"],
        "harm": r["expected_harm"],
        "event_s": sum(r["timings"].values())} for r in results])
    df["rank_pc"] = df["pc"].rank(ascending=False, method="first").astype(int)
    df["rank_harm"] = df["harm"].rank(ascending=False, method="first").astype(int)
    df["rank_shift"] = df["rank_pc"] - df["rank_harm"]
    rho = float(df["pc"].rank().corr(df["harm"].rank()))
    df = df.sort_values("rank_harm")
    show = df.head(args.top).copy()
    show["moved"] = np.where(show["rank_shift"].abs() >= 3, "*", "")
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 22,
                           "display.float_format", "{:.3g}".format):
        print(f"Survey of {len(df)} events (seed {args.seed}); ranked by expected harm "
              f"(* = rank moves by >=3 vs Pc rank)")
        print(show[["primary", "threat", "miss_km", "catastrophic", "fragments_true", "pc", "n_ge1", "encounters",
                    "harm", "rank_pc", "rank_harm", "moved"]].to_string(index=False))
    n_sl = int(df["primary"].str.startswith("STARLINK").sum())
    print(f"Starlink primaries: {n_sl} of {len(df)} ({100 * n_sl / len(df):.0f}%)")
    print(f"Spearman rank correlation Pc vs harm: {rho:.3f}; events moving >=3 places: "
          f"{int((df['rank_shift'].abs() >= 3).sum())} of {len(df)}; wall {wall:.1f} s on {workers} worker(s)")
    stem = f"consequence_survey{args.survey}_seed{args.seed}_{stamp}"
    df.to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(json.dumps(
        {"spearman_pc_vs_harm": rho, "wall_s": wall, "workers": workers, "params": params.__dict__,
         "assumptions": ASSUMPTIONS, "events": results}, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out_dir / (stem + '.csv')} and .json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primary", type=int, default=None, help="NORAD id of the primary (e.g. 25544)")
    ap.add_argument("--threat", type=int, default=None, help="force the threat NORAD id")
    ap.add_argument("--survey", type=int, default=None, help="number of random LEO payload events (includes ISS)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--days", type=float, default=3.0, help="closest-approach search window")
    ap.add_argument("--workers", type=int, default=None, help="default: $WORKERS or os.cpu_count()")
    ap.add_argument("--max-fragments", type=int, default=3000)
    ap.add_argument("--k", type=int, default=8, help="random mean anomalies per fragment per snapshot")
    ap.add_argument("--phases", type=int, default=16, help="satellite phases per day")
    ap.add_argument("--r-km", type=float, default=1.0, help="close-approach exposure radius")
    ap.add_argument("--sigma-km", type=float, default=1.0, help="isotropic position sigma for Pc")
    ap.add_argument("--hbr-m", type=float, default=20.0)
    ap.add_argument("--top", type=int, default=8, help="rows to print in the survey table")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    if (args.primary is None) == (args.survey is None):
        raise SystemExit("give exactly one of --primary or --survey")
    workers = args.workers or default_workers()
    params = Params(seed=args.seed, max_fragments=args.max_fragments, k_anomalies=args.k, phases=args.phases,
                    r_km=args.r_km, sigma_km=args.sigma_km, hbr_m=args.hbr_m)
    records = load_catalog(force=args.refresh)
    out_dir = data_dir() / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.primary is not None:
        _single(args, records, workers, params, out_dir, stamp)
    else:
        _survey(args, records, workers, params, out_dir, stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
