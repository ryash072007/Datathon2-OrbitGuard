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
| 1–2 Risk + decision | `python scripts/get_data.py`; `python -m orbitguard.decision.decision fit` then `eval` | Test L within noise of Windows (0.680); model trained on the VM | `lscpu` (s390x), training log with timing, metrics table |
| 3 Screener | `pip install sgp4`; `python -m orbitguard.catalog.run --primary 25544 --days 3 --target-km 10` and `--benchmark` | Same ranked burns as on Windows (TLEs refresh, so the event may differ); speed-up measured | `htop` during the run, speed-up table vs Windows |
| 4 Consequence | `python -m orbitguard.consequence.run --primary 25544` and `--survey 20 --seed 0` | Same shape of results; timings recorded | Survey timing on N cores |
| 5 Network + brief + app | `python -m orbitguard.network.run`; Granite big-endian GGUF (section below), `LLM_BACKEND=llamacpp`; Flask on 0.0.0.0 | Dashboard reachable from a browser, footer shows s390x/big, brief grounded | Dashboard screenshot from the VM, LLM log |
| 6 Full run | Containerise (Dockerfile on the official s390x image) and run end to end | One command runs the demo | `docker ps`, container logs, architecture screenshot |
| 7 Submission | Record the demo on the VM | Video shows the LinuxONE instance and model | Video, flowchart |

## LLM on the VM (decision, Phase 5/6)

The IBM labs weren't available to us, so we chose the stack ourselves: **IBM Granite 3.3 2B Instruct**
(`ibm-granite/granite-3.3-2b-instruct`) via `llama_cpp_python` (already in the VM image), `LLM_BACKEND=llamacpp`.

- s390x is big-endian, so GGUF files must be converted to big-endian. Little-endian GGUFs from Hugging Face won't
  load. Per [llama.cpp docs/build-s390x.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/build-s390x.md),
  convert the safetensors on the VM: `python convert_hf_to_gguf.py <model_dir> --outtype q8_0 --bigendian` (or
  `--outtype f16`). Q4_0/Q4_K/Q5_K/Q6_K/Q8_0 have s390x SIMD paths; avoid Q2_K/IQ2/IQ3 (slow scalar fallback).
- On Windows, test with a normal little-endian Granite GGUF (`ibm-granite/granite-3.3-2b-instruct-GGUF`).
- The template backend plus the grounding guard keep the demo working if the model fails.

## Known differences to watch

- xgboost is only on the VM; our code uses scikit-learn `HistGradientBoostingRegressor` on both.
- The VM image has torch, tensorflow, onnx and `llama_cpp_python`; Windows doesn't need them until Phase 3.
- Timing numbers for the pitch come from the VM only.

- **sgp4 on s390x:** there is no s390x wheel, so pip silently installs the pure-Python fallback (`sgp4.api.accelerated == False`), which made the screener ~70x slower on the VM (939 s). The Dockerfile and `vm_setup.sh` now build the C extension with `--no-binary=sgp4` and check it.

## NNPA (Telum on-chip accelerator) with TensorFlow, found on the z17 VM

- Hardware: machine type 9175 (z17); `/proc/cpuinfo` features include `nnpa`, `vxe2`, `dflt`. No `--privileged` needed.
- `ibm-zdnn-plugin` 2.3.0 is not a PluggableDevice: it installs `tensorflow/core/kernels/_z_ops.so` (links `libzdnn.so.0` in
  `/usr/local/lib`), which TensorFlow loads by itself. It adds a Grappler "ZRemapper" that rewrites MatMul+BiasAdd+activation into
  `_ZFusedMatMul` with `ZStickify`/`ZUnstickify` around it. `tf.config.list_physical_devices()` therefore shows only CPU, and the
  placer log shows CPU too; do not take that as proof that the accelerator is off.
- Switch: environment variable `NNPA_DEVICES`. `NNPA_DEVICES=0` disables the rewrite (pure CPU); unset or `1` enables it. Set it before importing TF.
- Evidence: run with `TF_CPP_MIN_LOG_LEVEL=0 TF_CPP_MAX_VLOG_LEVEL=3` and grep `Instantiating kernel .* = _ZFusedMatMul`
  (present with 1, absent with 0). Predictions also differ by up to 1.5e-3 (DLFLOAT16), another sign the NNPA ran. Only Keras graph
  execution (`model.predict`) is rewritten; eager ops are not.
- Speed-up grows with batch size (stickification overhead): 1.06x at 1k rows to 2.7x at 1M rows for a 134-256-256-128-1 MLP.
- `torch_nnpa` 1.5.0 also works (`torch_nnpa.device()` gives `nnpa:0`, tensors and matmul live on it), but we did not use it.
- The image's `llama_cpp_python` build includes `libggml-zdnn.so`; `n_gpu_layers=-1` made no speed difference for Granite q8_0 (about 1 tok/s).

## Granite conversion gotchas (VM)

- Run the converter inside the image (torch, transformers, numpy are already there). `scripts/convert_granite_bigendian.sh` no longer
  pip-installs; it takes `gguf` from the llama.cpp checkout (`gguf-py`), downloads with `huggingface_hub`, and stubs `sentencepiece`
  (no s390x wheel; the converter imports it before it looks for `tokenizer.model`, which Granite lacks).
- Mount a work directory outside the repo (`-v ~/granite_work:/granite_work -e WORK=/granite_work`); HOME is read-only for `--user`.
- Gotcha: scripts that start a `ProcessPoolExecutor` (spawn) need an `if __name__ == "__main__":` guard.
