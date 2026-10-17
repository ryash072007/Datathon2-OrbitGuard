"""Snap ML BoostingMachineClassifier as a "second opinion" P(final risk >= -6), scored on CPU or the IBM Z NNPA.

Path to the accelerator (docs: https://snapml.readthedocs.io):
  1. `fit` trains snapml.BoostingMachineClassifier and exports it as PMML (portable text, no pickle).
  2. The SAME PMML is re-imported with `snapml.import_model(path, input_type="pmml", tree_format=...)`:
       tree_format="compress_trees" -> CPU inference engine,
       tree_format="zdnn_tensors"   -> matrix-based inference on the Telum accelerator via libzdnn.
     On hosts without the accelerator (e.g. Windows, x86) the zdnn import is reported unavailable, never fatal.

CLI:  python -m orbitguard.zai.snap fit | eval
`eval` opens the sealed ESA test labels only after the model file is frozen (SHA-256 before and after).
Features are the decision layer's classifier features (clf_matrix), missing values filled with TRAIN medians.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ZAI_DIR = ROOT / "artifacts" / "zai"
MODEL_PATH = ZAI_DIR / "snapml_bmc.pmml"
META_PATH = ZAI_DIR / "snapml_metadata.json"
EVIDENCE_PATH = ZAI_DIR / "snapml_evidence.json"
DECISION_JOBLIB = ROOT / "artifacts" / "ml" / "decision.joblib"
SEED = 7
GRID = [{"num_round": r, "max_depth": d, "learning_rate": lr} for r in (50, 100, 300) for d in (2, 3, 5) for lr in (0.05, 0.1)]


# ----------------------------------------------------------------------------- platform probes
def snapml_version() -> str | None:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("snapml")
    except PackageNotFoundError:
        return None


def snapml_available() -> bool:
    try:
        import snapml  # noqa: F401
    except ImportError:
        return False
    return True


def nnpa_in_cpuinfo() -> bool:
    """True if the `features` line of /proc/cpuinfo lists nnpa (s390x Telum)."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any("nnpa" in line.lower().split() for line in text.splitlines() if line.lower().startswith("features"))


def zdnn_loaded() -> bool:
    """True if libzdnn is mapped into this process (Linux only)."""
    try:
        return "libzdnn" in Path("/proc/self/maps").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def platform_info() -> dict:
    return {"hostname": socket.gethostname(), "machine": platform.machine(), "byteorder": sys.byteorder,
            "python": platform.python_version(), "snapml_version": snapml_version(), "nnpa_in_cpuinfo": nnpa_in_cpuinfo()}


# ----------------------------------------------------------------------------- features
def featurize(tab, medians: dict) -> np.ndarray:
    """Decision-feature table -> float32 matrix in the stored column order, NaN filled with train medians."""
    import pandas as pd

    from orbitguard.decision.decision import clf_matrix
    X = clf_matrix(tab)[list(medians)].astype("float64").fillna(pd.Series(medians, dtype="float64"))
    return np.ascontiguousarray(X.to_numpy(), dtype=np.float32)


def train_table():
    import pandas as pd

    from orbitguard.decision.features import build_table
    from orbitguard.decision.train import DATA, usable_labels
    train = pd.read_csv(DATA / "train_data.csv")
    labels = usable_labels(train)
    return build_table(train[train["event_id"].isin(labels.index)], labels)


# ----------------------------------------------------------------------------- model loading / scoring
class Scorer:
    """A snapml model imported from PMML with one tree_format. `backend` says what actually runs."""

    def __init__(self, model, tree_format: str, requested: str):
        self.model, self.tree_format, self.requested = model, tree_format, requested

    @property
    def backend(self) -> str:
        return "snapml-zdnn" if self.tree_format == "zdnn_tensors" else "snapml-cpu"

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict_proba(np.ascontiguousarray(X, dtype=np.float32)))[:, 1].astype("float64")


def load_scorer(path: Path, tree_format: str, n_jobs: int | None = None) -> Scorer:
    """Import the PMML with the given tree_format. Raises RuntimeError if that format cannot be built here."""
    if not snapml_available():
        raise RuntimeError("snapml is not installed")
    import snapml
    try:
        model = snapml.import_model(str(path), input_type="pmml", tree_format=tree_format)
    except Exception as exc:  # snapml raises assorted types when libzdnn / NNPA is absent
        raise RuntimeError(f"snapml import with tree_format={tree_format} failed: {type(exc).__name__}: {exc}") from exc
    got = getattr(model, "optimized_tree_format_", tree_format)
    if tree_format == "zdnn_tensors" and got != "zdnn_tensors":
        raise RuntimeError(f"snapml selected tree_format={got} instead of zdnn_tensors")
    if n_jobs:
        try:
            model.set_params(n_jobs=n_jobs)
        except (ValueError, AttributeError, TypeError):
            pass  # n_jobs is a performance hint only
    return Scorer(model, got, tree_format)


def _bench_prefers_zdnn() -> bool:
    """True when the newest bench file records zDNN faster than CPU on the smallest batch (a live request is one row)."""
    benches = sorted(ZAI_DIR.glob("snapml_bench_*.json"), key=lambda p: p.stat().st_mtime)
    if not benches:
        return True  # unmeasured host: try the accelerator, as before
    rows = [r for r in json.loads(benches[-1].read_text()).get("table", []) if r.get("nnpa_status") == "ready"]
    if not rows:
        return False
    smallest = min(rows, key=lambda r: r["rows"])
    return float(smallest.get("speedup") or 0.0) > 1.0


def load_best_scorer(path: Path = MODEL_PATH) -> Scorer:
    """The faster measured path: zDNN only if this host's bench shows it beating CPU at small batch sizes.

    On the z17 Community Cloud VM (3 vCPUs) Snap ML's compressed CPU trees were faster than zdnn_tensors at every
    size, with identical predictions, so the live second opinion uses CPU there. SNAPML_TREE_FORMAT overrides.
    """
    forced = os.environ.get("SNAPML_TREE_FORMAT")
    if forced:
        return load_scorer(path, forced)
    if nnpa_in_cpuinfo() and _bench_prefers_zdnn():
        try:
            return load_scorer(path, "zdnn_tensors")
        except RuntimeError as exc:
            print(f"snapml zdnn unavailable, using CPU: {exc}", file=sys.stderr)
    return load_scorer(path, "compress_trees")


# ----------------------------------------------------------------------------- fit
def _new_model(params: dict, n_jobs: int):
    from snapml import BoostingMachineClassifier
    return BoostingMachineClassifier(random_state=SEED, n_jobs=n_jobs, **params)


def cmd_fit(out_dir: Path = ZAI_DIR, tab=None) -> dict:
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import StratifiedKFold

    from orbitguard.decision.decision import clf_matrix
    from orbitguard.nnpa.bench import HIGH_RISK
    if not snapml_available():
        raise SystemExit("snapml is not installed: pip install snapml (or pip install -e '.[zai]')")
    tab = train_table() if tab is None else tab
    y = (tab["target"].to_numpy() >= HIGH_RISK).astype("float32")
    medians = {c: float(v) if np.isfinite(v) else 0.0 for c, v in clf_matrix(tab).median().items()}
    X = featurize(tab, medians)
    n_jobs = os.cpu_count() or 1
    print(f"train events {len(y)}, high-risk {int(y.sum())}, features {X.shape[1]}")

    cv = StratifiedKFold(5, shuffle=True, random_state=SEED)
    results = []
    for params in GRID:
        aps, aucs = [], []
        for tr, te in cv.split(X, y):
            m = _new_model(params, n_jobs)
            m.fit(X[tr], y[tr])
            p = m.predict_proba(X[te])[:, 1]
            aps.append(average_precision_score(y[te], p))
            aucs.append(roc_auc_score(y[te], p))
        results.append({**params, "cv_ap_mean": float(np.mean(aps)), "cv_ap_std": float(np.std(aps)),
                        "cv_auc_mean": float(np.mean(aucs))})
        print(f"  {params}  AP {results[-1]['cv_ap_mean']:.4f}  AUC {results[-1]['cv_auc_mean']:.4f}")
    best = max(results, key=lambda r: r["cv_ap_mean"])
    chosen = {k: best[k] for k in ("num_round", "max_depth", "learning_rate")}
    model = _new_model(chosen, n_jobs)
    model.fit(X, y)

    out_dir.mkdir(parents=True, exist_ok=True)
    pmml = out_dir / MODEL_PATH.name
    model.export_model(str(pmml), "pmml")
    cpu = load_scorer(pmml, "compress_trees")
    roundtrip = float(np.max(np.abs(cpu.predict_proba(X) - model.predict_proba(X)[:, 1])))
    meta = {
        "model_file": pmml.name, "model_sha256": sha256_file(pmml), "export_format": "pmml",
        "high_risk_threshold_log10_pc": HIGH_RISK, "label": "final risk >= -6",
        "feature_names": list(medians), "train_medians": medians, "hyperparameters": chosen,
        "cv": {"scheme": "5-fold stratified on TRAIN events only; selection metric = average precision",
               "grid": results, "chosen": best},
        "train_events": int(len(y)), "train_positives": int(y.sum()),
        "roundtrip_max_abs_diff_native_vs_imported_cpu": roundtrip,
        "fitted_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **platform_info(),
    }
    (out_dir / META_PATH.name).write_text(json.dumps(meta, indent=2, allow_nan=False), encoding="utf-8")
    print(f"chosen {chosen}; PMML roundtrip max|diff| {roundtrip:.2e}; sha256 {meta['model_sha256'][:16]}...")
    print(f"saved {pmml}")
    return meta


# ----------------------------------------------------------------------------- eval
def _ap(y, s) -> float:
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, s))


def paired_bootstrap_ap_diff(y: np.ndarray, a: np.ndarray, b: np.ndarray, n: int = 2000, seed: int = SEED) -> dict:
    """AP(a) - AP(b) with a paired percentile 95% CI over event resamples. Resamples without a positive are counted."""
    rng = np.random.default_rng(seed)
    diffs, skipped = [], 0
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() == 0:
            skipped += 1
            continue
        diffs.append(_ap(y[i], a[i]) - _ap(y[i], b[i]))
    if not diffs:
        return {"status": "undefined", "reason": "no bootstrap resample contained a positive", "skipped": skipped}
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"status": "ready", "point": _ap(y, a) - _ap(y, b), "ci95": [float(lo), float(hi)],
            "ci_excludes_zero": bool(lo > 0 or hi < 0), "resamples": len(diffs), "skipped_resamples": skipped}


def _safe_metrics(y: np.ndarray, s: np.ndarray, probability: bool) -> dict:
    from sklearn.metrics import brier_score_loss, roc_auc_score
    fns = {"average_precision": lambda: _ap(y, s), "roc_auc": lambda: float(roc_auc_score(y, s)),
           "brier": (lambda: float(brier_score_loss(y, s))) if probability else None}
    out: dict = {}
    for name, fn in fns.items():
        if fn is None:
            out[name] = {"status": "not_applicable", "reason": "score is not a probability"}
            continue
        try:
            v = fn()
            out[name] = {"status": "ready", "value": v} if np.isfinite(v) else {"status": "undefined", "value": None}
        except Exception as exc:  # reported, not dropped
            out[name] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    return out


def _val(m: dict, k: str):
    return m[k].get("value", m[k].get("error"))


def cmd_eval(model_path: Path = MODEL_PATH, evidence_path: Path = EVIDENCE_PATH) -> dict:
    import pandas as pd

    from orbitguard.decision.evaluate import released_test_labels
    from orbitguard.decision.features import build_table
    from orbitguard.decision.train import DATA
    from orbitguard.nnpa.bench import HIGH_RISK
    model_path = Path(model_path)
    if not model_path.exists():
        raise ValueError(f"Freeze {model_path.name} (run `fit`) before opening final test labels")
    meta = json.loads(model_path.with_name(META_PATH.name).read_text(encoding="utf-8"))
    sha_before = sha256_file(model_path)
    if sha_before != meta["model_sha256"]:
        raise ValueError("Snap ML model file does not match its metadata SHA-256; refit before evaluating")
    cpu = load_scorer(model_path, "compress_trees")
    test = pd.read_csv(DATA / "test_data.csv")
    priv = released_test_labels(model_path)  # first label access; the model above is already frozen
    tab = build_table(test, priv)
    y = (tab["target"].to_numpy() >= HIGH_RISK).astype(int)
    X = featurize(tab, meta["train_medians"])
    p = cpu.predict_proba(X)
    naive = tab["naive_risk"].to_numpy(dtype=float)

    comparisons = {"vs_naive_latest_risk": paired_bootstrap_ap_diff(y, p, naive)}
    msg = "artifacts/ml/decision.joblib not found; re-run eval after decision-fit"
    if DECISION_JOBLIB.exists():
        import joblib

        from orbitguard.decision.decision import proba
        p_dec = proba(joblib.load(DECISION_JOBLIB)["classifier"], tab)
        decision_block = {"status": "ready", "metrics": _safe_metrics(y, p_dec, True)}
        comparisons["vs_decision_layer_p_high"] = paired_bootstrap_ap_diff(y, p, p_dec)
    else:
        decision_block = {"status": "missing", "message": msg}
        comparisons["vs_decision_layer_p_high"] = {"status": "missing", "message": msg}

    try:
        pz = load_scorer(model_path, "zdnn_tensors").predict_proba(X)
        zdnn = {"status": "ready", "metrics": _safe_metrics(y, pz, True), "max_abs_diff_vs_cpu": float(np.max(np.abs(pz - p)))}
    except RuntimeError as exc:
        zdnn = {"status": "unavailable", "reason": str(exc)}

    sha_after = sha256_file(model_path)
    if sha_after != sha_before:
        raise ValueError("Snap ML model changed during evaluation; no evidence written")
    evidence = {
        "status": "ready", "source": "ESA Collision Avoidance Challenge test set; sealed released labels",
        "test_events": int(len(y)), "high_risk_test_events": int(y.sum()), "label": "final risk >= -6",
        "snapml_cpu": _safe_metrics(y, p, True), "snapml_zdnn": zdnn,
        "naive_latest_risk": _safe_metrics(y, naive, False), "decision_layer_p_high": decision_block,
        "paired_bootstrap_ap_difference": comparisons,
        "bootstrap": {"method": "paired percentile, resample events", "seed": SEED},
        "fingerprints": {"snapml_sha256_before_labels": sha_before, "snapml_sha256_after_evaluation": sha_after},
        "model": {"hyperparameters": meta["hyperparameters"], "snapml_version_at_fit": meta.get("snapml_version"),
                  "fit_host": meta.get("hostname"), "fit_machine": meta.get("machine")},
        "platform": platform_info(), "evaluated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "limitations": ["Hyperparameters were chosen by training-set cross-validation; the test set is a retrospective "
                        "public set already used by earlier project versions.",
                        "Second opinion only: it never changes the Act/Wait/Monitor action."],
    }
    evidence_path = Path(evidence_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    m = evidence["snapml_cpu"]
    print(f"test events {len(y)}, high-risk {int(y.sum())}; snapml AP {_val(m, 'average_precision')} "
          f"AUC {_val(m, 'roc_auc')} Brier {_val(m, 'brier')}")
    print(json.dumps(comparisons, indent=1))
    print(f"zdnn: {zdnn['status']}; wrote {evidence_path}")
    return evidence


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fit", "eval"])
    ap.add_argument("--path", type=Path, default=MODEL_PATH)
    a = ap.parse_args()
    if a.cmd == "fit":
        cmd_fit(a.path.parent)
    else:
        cmd_eval(a.path, a.path.with_name(EVIDENCE_PATH.name))


if __name__ == "__main__":
    main()
