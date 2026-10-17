"""Benchmark Snap ML tree-ensemble inference: CPU (compress_trees) vs IBM Z accelerator (zdnn_tensors).

Both runs import the SAME PMML file written by `python -m orbitguard.zai.snap fit`.
The zdnn rows are reported "unavailable" on hosts without NNPA/libzdnn (e.g. Windows); nothing crashes.

CLI:  python -m orbitguard.zai.bench [--sizes 1000,10000,100000,1000000] [--max-rows N] [--repeats 3]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path

import numpy as np

from orbitguard.nnpa.bench import SIZES, synthetic_rows
from orbitguard.zai.snap import (MODEL_PATH, META_PATH, ZAI_DIR, load_scorer, nnpa_in_cpuinfo, platform_info,
                                 featurize, snapml_available, train_table, zdnn_loaded)


def real_rows(meta: dict) -> np.ndarray:
    return featurize(train_table(), meta["train_medians"])


def time_scorer(scorer, x: np.ndarray, repeats: int) -> float:
    scorer.predict_proba(x[: min(len(x), 10_000)])  # warm-up
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        scorer.predict_proba(x)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def run(sizes: list[int], repeats: int, model_path: Path = MODEL_PATH) -> dict:
    host = os.environ.get("BENCH_HOST") or socket.gethostname()
    res: dict = {"host": host, **platform_info(), "cpu_count": os.cpu_count(), "sizes": sizes, "repeats": repeats,
                 "model": str(model_path.name), "statistic": "median wall seconds over repeats"}
    if not snapml_available():
        res.update(status="unavailable", reason="snapml is not installed", table=[])
        return res
    if not model_path.exists():
        res.update(status="unavailable", reason=f"{model_path.name} missing; run `python -m orbitguard.zai.snap fit`", table=[])
        return res
    meta = json.loads(model_path.with_name(META_PATH.name).read_text(encoding="utf-8"))
    n_jobs = os.cpu_count() or 1
    cpu = load_scorer(model_path, "compress_trees", n_jobs=n_jobs)
    try:
        z = load_scorer(model_path, "zdnn_tensors", n_jobs=n_jobs)
        z_reason = None
    except RuntimeError as exc:
        z, z_reason = None, str(exc)
    real = real_rows(meta)
    table = []
    for n in sizes:
        x = synthetic_rows(real, n)
        row: dict = {"rows": n}
        pc = cpu.predict_proba(x[: min(n, 100_000)])
        tc = time_scorer(cpu, x, repeats)
        row.update(cpu_seconds=round(tc, 5), cpu_rows_per_s=round(n / tc))
        if z is None:
            row.update(nnpa_status="unavailable", nnpa_rows_per_s=None, speedup=None, max_abs_diff=None)
        else:
            tz = time_scorer(z, x, repeats)
            pz = z.predict_proba(x[: min(n, 100_000)])
            row.update(nnpa_status="ready", nnpa_seconds=round(tz, 5), nnpa_rows_per_s=round(n / tz),
                       speedup=round(tc / tz, 2), max_abs_diff=float(np.max(np.abs(pc - pz))))
        table.append(row)
        print(f"n={n:>8}  cpu={row['cpu_rows_per_s']:>11,} rows/s  nnpa={row['nnpa_rows_per_s'] or row['nnpa_status']}"
              f"  speedup={row['speedup']}", flush=True)
        del x
    res.update(status="ready", nnpa_available=z is not None, nnpa_unavailable_reason=z_reason,
               libzdnn_loaded=zdnn_loaded(), cpu_tree_format=cpu.tree_format,
               nnpa_tree_format=None if z is None else z.tree_format, table=table)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", default=",".join(map(str, SIZES)))
    ap.add_argument("--max-rows", type=int, default=None, help="drop sizes above this")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--model", type=Path, default=MODEL_PATH)
    a = ap.parse_args()
    sizes = [int(s) for s in a.sizes.split(",") if a.max_rows is None or int(s) <= a.max_rows]
    res = run(sizes, a.repeats, a.model)
    ZAI_DIR.mkdir(parents=True, exist_ok=True)
    dest = ZAI_DIR / f"snapml_bench_{res['host']}.json"
    dest.write_text(json.dumps(res, indent=2, allow_nan=False), encoding="utf-8")
    print(f"status={res['status']} nnpa_available={res.get('nnpa_available')} libzdnn_loaded={res.get('libzdnn_loaded')} "
          f"nnpa_in_cpuinfo={nnpa_in_cpuinfo()} -> {dest}")


if __name__ == "__main__":
    main()
