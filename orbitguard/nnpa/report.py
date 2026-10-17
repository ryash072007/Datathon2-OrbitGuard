"""Print the CPU vs NNPA benchmark table from the newest data/out/nnpa_bench_*.json (written by orbitguard.nnpa.bench)."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "out"


def main() -> None:
    files = sorted(OUT.glob("nnpa_bench_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit("no nnpa_bench_*.json found: run `python -m orbitguard.nnpa.bench` first")
    d = json.loads(files[-1].read_text(encoding="utf-8"))
    print(f"Keras MLP scoring conjunctions: CPU vs NNPA ({files[-1].name})")
    print(f"plugin: ibm-zdnn-plugin {d['ibm_zdnn_plugin_version']} | machine type {d['sysinfo_type']}")
    print(f"{'rows':>10} {'CPU rows/s':>12} {'NNPA rows/s':>12} {'speed-up':>9}")
    for r in d["table"]:
        print(f"{r['rows']:>10,} {r['cpu_rows_per_s']:>12,.0f} {r['nnpa_rows_per_s']:>12,.0f} {r['speedup']:>8.2f}x")
    print("max |CPU - NNPA| prediction diff:", round(d["max_abs_diff_prob"], 4))


if __name__ == "__main__":
    main()
