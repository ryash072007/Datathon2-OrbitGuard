"""Benchmark Keras MLP inference with the IBM Z NNPA accelerator OFF vs ON (TensorFlow + ibm-zdnn-plugin).

How the accelerator is switched (found on the VM image, see docs/porting.md):
  * ibm-zdnn-plugin ships tensorflow/core/kernels/_z_ops.so, which TensorFlow loads by itself. It registers a
    Grappler "ZRemapper" that rewrites MatMul+BiasAdd+activation into `_ZFusedMatMul` (zDNN / NNPA) kernels.
  * The environment variable NNPA_DEVICES controls it: NNPA_DEVICES=0 leaves the graph untouched (pure CPU),
    anything else (or unset) enables the rewrite. tf.config.list_physical_devices() shows only CPU in both cases,
    because the plugin works through kernels and not through a PluggableDevice.
  * Evidence of NNPA use: TF_CPP_MAX_VLOG_LEVEL=3 logs "Instantiating kernel ... = _ZFusedMatMul" (counted below).

CLI:  python -m src.nnpa.bench [--epochs 4] [--sizes 1000,10000,100000,1000000] [--skip-train]
Internal (child process):  python -m src.nnpa.bench --child off|on --out file.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "models" / "nnpa_mlp.keras"
META_PATH = ROOT / "models" / "nnpa_mlp_meta.json"
REAL_PATH = ROOT / "models" / "nnpa_real_features.npy"
HIGH_RISK = -6.0
SEED = 7
SIZES = [1_000, 10_000, 100_000, 1_000_000]
MAX_CHUNK = 10_000  # rows per internal predict step


def data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else ROOT / "data"


# ----------------------------------------------------------------------------- features
def build_matrix() -> tuple[np.ndarray, np.ndarray, dict]:
    """Decision-feature table -> standardised float32 matrix, 0/1 labels (final risk >= -6), preprocessing meta."""
    import pandas as pd

    from src.risk.features import build_table
    from src.risk.train import feature_matrix, usable_labels

    train = pd.read_csv(data_dir() / "raw" / "cac" / "train_data.csv")
    labels = usable_labels(train)
    tab = build_table(train[train["event_id"].isin(labels.index)], labels)
    y = (tab["target"].to_numpy() >= HIGH_RISK).astype("float32")
    X, levels = feature_matrix(tab, floor=-20.0)
    num_cols = [c for c in X.columns
                if c not in ("c_object_type", "mission_id") and np.issubdtype(X[c].dtype, np.number)]
    num = X[num_cols].astype("float64")
    med = num.median().fillna(0.0)
    num = num.fillna(med)
    mu, sd = num.mean(), num.std(ddof=0).replace(0.0, 1.0)
    parts = [((num - mu) / sd).to_numpy()]
    for c in ("c_object_type", "mission_id"):
        lv = np.array(levels[c], dtype=object)
        parts.append((X[c].astype(object).to_numpy()[:, None] == lv[None, :]).astype("float64"))
    M = np.clip(np.hstack(parts), -10, 10).astype("float32")
    meta = {"num_cols": num_cols, "levels": {c: [str(v) for v in levels[c]] for c in levels},
            "n_features": int(M.shape[1]), "n_events": int(M.shape[0]), "positives": int(y.sum())}
    return M, y, meta


def synthetic_rows(real: np.ndarray, n: int, seed: int = SEED) -> np.ndarray:
    """n rows resampled (with replacement) from the real feature rows plus small Gaussian jitter."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(real), size=n)
    out = real[idx] + rng.normal(0.0, 0.05, size=(n, real.shape[1])).astype("float32")
    return out.astype("float32")


# ----------------------------------------------------------------------------- training
def train_model(epochs: int) -> dict:
    os.environ["NNPA_DEVICES"] = "0"  # train on plain CPU; the accelerator is for inference
    import tensorflow as tf

    tf.keras.utils.set_random_seed(SEED)
    X, y, meta = build_matrix()
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(REAL_PATH, X)  # reused by the benchmark children
    model = tf.keras.Sequential([
        tf.keras.layers.Input((X.shape[1],)),
        tf.keras.layers.Dense(256, activation="relu"),
        tf.keras.layers.Dense(256, activation="relu"),
        tf.keras.layers.Dense(128, activation="relu"),
        tf.keras.layers.Dense(1, activation="sigmoid"),
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=[tf.keras.metrics.AUC(name="auc")])
    t0 = time.perf_counter()
    h = model.fit(X, y, epochs=epochs, batch_size=128, validation_split=0.2, verbose=0)
    meta["train_seconds"] = round(time.perf_counter() - t0, 1)
    meta["history"] = {k: [round(float(v), 4) for v in vs] for k, vs in h.history.items()}
    model.save(MODEL_PATH)
    META_PATH.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"trained MLP on {meta['n_events']} events ({meta['positives']} positive), "
          f"{meta['n_features']} features, {meta['train_seconds']}s -> {MODEL_PATH}")
    return meta


# ----------------------------------------------------------------------------- child: one accelerator setting
def child(mode: str, out: Path, sizes: list[int]) -> None:
    os.environ["NNPA_DEVICES"] = "1" if mode == "on" else "0"  # must be set before TensorFlow is imported
    import tensorflow as tf

    devices = [f"{d.device_type}:{d.name}" for d in tf.config.list_physical_devices()]
    model = tf.keras.models.load_model(MODEL_PATH)
    real = np.load(REAL_PATH)
    res = {"mode": mode, "nnpa_devices_env": os.environ["NNPA_DEVICES"], "devices": devices,
           "tf_version": tf.__version__, "rows": {}}
    ref = synthetic_rows(real, min(10_000, max(sizes)))
    np.save(out.parent / f"{out.stem}.pred.npy", model.predict(ref, batch_size=MAX_CHUNK, verbose=0).ravel())
    for n in sizes:
        x = synthetic_rows(real, n)
        bs = min(n, MAX_CHUNK)
        model.predict(x[: min(n, 2 * bs)], batch_size=bs, verbose=0)  # warm-up
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            model.predict(x, batch_size=bs, verbose=0)
            times.append(time.perf_counter() - t0)
        med = sorted(times)[1]
        res["rows"][str(n)] = {"predict_batch_size": bs, "seconds": [round(t, 4) for t in times],
                               "rows_per_s_median": round(n / med), "rows_per_s_best": round(n / min(times))}
        print(f"[{mode}] n={n:>8} rows/s median={n / med:,.0f} best={n / min(times):,.0f}", flush=True)
        del x
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")


def evidence(mode: str) -> dict:
    """Tiny run with verbose TF logs in a fresh process: count Z kernels instantiated / graph rewrites."""
    code = ("import numpy as np, tensorflow as tf; m=tf.keras.models.load_model(%r); "
            "m.predict(np.zeros((64,m.input_shape[1]),'float32'),verbose=0)" % str(MODEL_PATH))
    env = dict(os.environ, NNPA_DEVICES="1" if mode == "on" else "0", TF_CPP_MIN_LOG_LEVEL="0",
               TF_CPP_MAX_VLOG_LEVEL="3", PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=900)
    log = p.stderr + p.stdout
    inst = [(n, k) for n, k in re.findall(r"Instantiating kernel for node: \{\{node ([^}]*)\}\} = (_?Z\w+)", log)
            if k != "ZipDataset"]  # ZipDataset is a tf.data op, not an NNPA kernel
    plain = re.findall(r"Instantiating kernel for node: \{\{node [^}]*\}\} = (MatMul|_FusedMatMul|BiasAdd)\[", log)
    return {"z_kernels_instantiated": len(inst), "z_kernel_types": sorted({k for _, k in inst}),
            "z_kernel_nodes_sample": [n for n, _ in inst][:4], "plain_matmul_kernels_instantiated": len(plain),
            "zremapper_log_lines": log.count("ZRemapper"), "returncode": p.returncode}


def machine_type() -> str | None:
    try:
        for line in Path("/proc/sysinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Type:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def plugin_version() -> str | None:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("ibm-zdnn-plugin")
    except PackageNotFoundError:
        return None


# ----------------------------------------------------------------------------- orchestrator
def run_child(mode: str, out: Path, sizes: list[int]) -> dict:
    env = dict(os.environ, PYTHONPATH=str(ROOT), NNPA_DEVICES="1" if mode == "on" else "0")
    subprocess.run([sys.executable, "-m", "src.nnpa.bench", "--child", mode, "--out", str(out),
                    "--sizes", ",".join(map(str, sizes))], check=True, env=env, cwd=ROOT)
    return json.loads(out.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--sizes", default=",".join(map(str, SIZES)))
    ap.add_argument("--skip-train", action="store_true")
    ap.add_argument("--child", choices=["off", "on"])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    sizes = [int(s) for s in a.sizes.split(",")]
    if a.child:
        child(a.child, a.out, sizes)
        return

    if not (a.skip_train and MODEL_PATH.exists() and REAL_PATH.exists()):
        train_model(a.epochs)
    host = os.environ.get("BENCH_HOST") or socket.gethostname()  # inside docker pass -e BENCH_HOST=$(hostname)
    out_dir = data_dir() / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    f_off, f_on = out_dir / f"nnpa_tmp_{host}_off.json", out_dir / f"nnpa_tmp_{host}_on.json"
    off = run_child("off", f_off, sizes)
    on = run_child("on", f_on, sizes)
    diff = np.abs(np.load(f_off.with_suffix(".pred.npy")) - np.load(f_on.with_suffix(".pred.npy")))
    ev_off, ev_on = evidence("off"), evidence("on")
    nnpa_ok = "_ZFusedMatMul" in ev_on["z_kernel_types"] and "_ZFusedMatMul" not in ev_off["z_kernel_types"]
    table = []
    for n in sizes:
        c, z = off["rows"][str(n)]["rows_per_s_median"], on["rows"][str(n)]["rows_per_s_median"]
        table.append({"rows": n, "cpu_rows_per_s": c, "nnpa_rows_per_s": z, "speedup": round(z / c, 2)})
        print(f"n={n:>8}  cpu={c:>10,}  nnpa={z:>10,}  speedup={z / c:.2f}x")
    result = {
        "host": host, "machine": platform.machine(), "sysinfo_type": machine_type(),
        "tf_version": on["tf_version"], "ibm_zdnn_plugin_version": plugin_version(),
        "nnpa_available": bool(nnpa_ok),
        "how_enabled": "ibm-zdnn-plugin Grappler ZRemapper loaded by TensorFlow; NNPA_DEVICES=0 disables, default enables",
        "reason_if_unavailable": None if nnpa_ok else "no _Z* kernels were instantiated with NNPA_DEVICES=1",
        "devices_off": off["devices"], "devices_on": on["devices"],
        "evidence_off": ev_off, "evidence_on": ev_on,
        "model": str(MODEL_PATH.relative_to(ROOT)), "table": table,
        "max_abs_diff_prob": float(diff.max()), "mean_abs_diff_prob": float(diff.mean()),
        "diff_rows": int(len(diff)), "cpu_count": os.cpu_count(),
        "meta": json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else None,
        "raw_off": off["rows"], "raw_on": on["rows"],
    }
    dest = out_dir / f"nnpa_bench_{host}.json"
    dest.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for f in out_dir.glob(f"nnpa_tmp_{host}_*"):
        f.unlink()
    print(f"nnpa_available={nnpa_ok}  max|diff|={diff.max():.5f}  mean|diff|={diff.mean():.6f}  -> {dest}")


if __name__ == "__main__":
    main()
