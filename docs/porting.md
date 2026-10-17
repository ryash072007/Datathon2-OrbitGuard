# Porting to LinuxONE: plan per phase

We develop on Windows in a venv pinned to the VM image's versions (`requirements.txt`). Each phase is ported
and checked on the LinuxONE VM (s390x, big-endian, Ubuntu 24.04, official Jupyter ML container) as soon as it
is done, not all at the end.

## Rules that keep porting trivial (apply while writing code)

- **Same versions everywhere.** Only add a dependency after checking it installs on s390x (pure Python or has an
  s390x wheel). Record it in `requirements.txt` and in the README credits.
- **No binary artefacts cross machines.** Never copy pickles, joblib files or models from Windows to the VM.
  Retrain on the VM with the same script (it's cheap, and "trained on LinuxONE" is evidence for the judges).
  Data moves as CSV or JSON only.
- **Endianness.** No `struct`, `np.frombuffer` or `.tofile` with implicit byte order. If raw bytes are
  unavoidable, state the order explicitly (`'<f8'`).
- **Multiprocessing works under both spawn (Windows) and fork (Linux).** Worker functions live at module top
  level, entry points sit behind `if __name__ == "__main__":`, and workers get explicit arguments instead of
  globals. Worker count is `os.cpu_count()` unless overridden.
- **Paths and text.** Use `pathlib` only, with paths relative to the repo root and no drive letters.
  `.gitattributes` keeps LF line endings. Write files as UTF-8 explicitly.
- **Config through environment variables** (`.env` is gitignored): data dir, worker count, LLM endpoint.
- **Every phase has one entry-point command** that runs the same way on both machines.

## Moving code to the VM (every phase)

```bash
git pull                                   # on the VM, inside the repo clone
pip install -r requirements.txt            # inside the Jupyter ML container, or a venv on the VM
python -m pytest tests -q                  # same smoke tests as on Windows
```

Data comes down on the VM with the same download script. Don't scp it from the PC.

## Per-phase checklist

| Phase | Port step on the VM | Done when | Evidence to capture (`docs/evidence/`) |
| --- | --- | --- | --- |
| 1 Risk model | Download data, run the training script, run the eval script | Metrics within noise of the Windows run; model trained on the VM | `lscpu` (s390x), training log with timing, metrics table |
| 2 Screener | `pip install sgp4`; run the screener on the same conjunction with 1 worker and with N workers | Same ranked burns as on Windows; speed-up measured | Core-utilisation screenshot (`htop`) during the run, speed-up table |
| 3 Brief + app | LLM path that runs on the VM (Lab 2 approach / `llama_cpp_python` from the image, or an API), template fallback; start Flask bound to 0.0.0.0 | Dashboard reachable from a browser and shows the brief | Screenshot of the dashboard served from the VM, the LLM running |
| 4 Full run | Containerise (Dockerfile using the official s390x image as base) and run end to end | One command runs the demo | `docker ps`, container logs, architecture screenshot |
| 5 Submission | Record the demo on the VM | Video shows the LinuxONE instance and model | Video, flowchart |

## Known differences to watch

- xgboost is only on the VM; our code uses scikit-learn `HistGradientBoostingRegressor` on both.
- The VM image has torch, tensorflow, onnx and `llama_cpp_python`; Windows doesn't need them until Phase 3.
- Timing numbers for the pitch come from the VM only.
