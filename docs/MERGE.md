# How the two builds were combined

Two in-event builds of the same idea went into this repository, with their git histories preserved:

- **A: `IBM-Datathon`** (cascade-aware screener). The real CelesTrak catalogue, a consequence engine, a super-spreader network, IBM Granite on the box, a hash-chained audit log, an NNPA benchmark, a Jinja dashboard and a Dockerfile.
- **B: `ibmdatathon`** (OrbitGuard). A strict evaluation process, NASA-validated collision probability, a 50-scenario synthetic planner with abstention, a React console, and gunicorn + systemd on LinuxONE. Every number it reports was measured on s390x.

Both target the same theme (Real-Time AI for Critical Decisions) and the same ESA dataset. Both found that the "copy the latest CDM" baseline is hard to beat.

## Differences

| Area | A: IBM-Datathon | B: ibmdatathon (OrbitGuard) | Combined |
| --- | --- | --- | --- |
| Orbits | Real CelesTrak catalogue (~18.6k objects), SGP4, J2 burn deltas | Synthetic 8-object neighbourhood, two-body DOP853 | Both: synthetic suite for controlled evidence, real catalogue for the live demo |
| Collision probability | Small-HBR isotropic approximation, 1 km sigma | Encounter-plane Gaussian integral, matches NASA CARA cases to 3e-6 | B's integral everywhere, including on real SGP4 states (`catalog/collision.py`) |
| Burn acceptance | Miss target plus a count of new close approaches under 5 km | Every encounter Pc ≤ 1e-4 at 0.5x/1x/2x sigma; abstain if nothing passes | A's miss target AND B's all-object Pc rule; pair-only vs OrbitGuard comparison; explicit abstention |
| Miss distance | Minimum over 1 s SGP4 samples | Exact TCA refinement | 1 s samples refined to the rectilinear TCA. This fixed a bias of up to v_rel × 0.5 s: the ISS event is 3.89 km, not 4.98 km |
| ESA ML | HGB residual (negative result) + Act/Wait/Monitor layer: CV rules, calibrated logistic P(high), quantile-HGB 80% interval | HGB residual with frozen-model SHA256, sealed labels, bootstrap CIs, triage classifier, missed-alert guard | B's pipeline stays the validated default. A's decision layer runs beside it in every forecast and replay, evaluated through B's sealed-label path with fingerprints |
| Consequence | NASA SBM breakup, 30-day J2 debris density, expected harm = Pc × encounters, survey (Spearman 0.78) | None | A's engine, now with B's Pc |
| Network | Catalogue-wide 24 h close-approach graph, super-spreader score | None | Kept; exposed in the API and console |
| GenAI | Granite 3.3 2B on s390x (big-endian GGUF, llama.cpp) + numeric grounding guard + template fallback | None (deterministic templates only) | Granite writes the brief. It now narrates the Pc-gated recommendation and pair-only hazard, and the guard still blocks any invented number. GenAI never decides |
| Accountability | Hash-chained JSONL audit log (briefs, screens) | Fingerprinted artefacts; update IDs for replays | One audit chain recording replayed forecasts, screens (synthetic and live), briefs and the operator's accept / reject / defer |
| IBM Z specifics | NNPA (Telum) TensorFlow benchmark on z17 (2.67x at 1M rows); sgp4 C extension built on s390x; Granite big-endian | Native apt stack on s390x, gunicorn + hardened systemd unit, all metrics measured on LinuxONE | All of it, plus a Platform section in Validation (architecture, endianness, machine type, NNPA flag, sgp4 acceleration, container, LLM) |
| UI | Flask + Jinja + vanilla JS dashboard | React + TypeScript + Vite, three.js globes, Recharts, Validation page | B's console plus a new **Live catalogue** tab, Act/Wait/Monitor card in Encounters, decision and platform evidence in Validation, operator buttons and audit panel |
| Deploy | Dockerfile on the official LinuxONE image | systemd + gunicorn, rsync/tunnel helper | Multi-stage Dockerfile (React build + s390x image + gunicorn) and the systemd path |
| Tests | 43 (screener, consequence, network, brief, audit, decision) | 63 (API, ML leakage, physics, guard, triage, replay) | 140+ in one suite, plus new tests for the integration seams |

## What changed in code

1. **`orbitguard/catalog/collision.py`** (new). SGP4 states go into `physics.risk.collision_probability` with a prescribed TLE RTN covariance (0.5 / 1 / 0.5 km per object), swept at 0.5x, 1x and 2x. It symmetrises the rotated covariance, because B's strict input check rejected round-off on km-scale sigmas.
2. **`orbitguard/catalog/screen.py`**. Miss refinement to the linear TCA. Worst-case Pc for the threat and every other close approach. An `accepted` column. `recommend()` returns `no_action` / `pair_only` / `orbitguard` with abstention.
3. **`orbitguard/consequence/`**. `pc_isotropic` is now the exact disk integral, and the event assessment uses the encounter-plane Pc.
4. **`orbitguard/decision/`** (A's `src/risk`). Shares B's data directory. Labels are opened only through `ml.data.read_labels_after_freeze` once `decision.joblib` exists. `decision-eval` writes `decision_evidence.json` with SHA256 before and after.
5. **`orbitguard/ml/service.py`**. Every forecast and replay step carries `decision`: action, P(high), interval and reasons.
6. **`orbitguard/live.py`** (new). Live-catalogue, network, survey, brief, audit, operator and platform endpoints, run as background jobs.
7. **`orbitguard/api.py`**. Registers the blueprint and appends replayed forecasts and synthetic screens to the audit chain.
8. **`orbitguard/__main__.py`**. One CLI: `decision-fit/eval`, `screen-live`, `consequence`, `validate-breakup`, `network`, `brief`, `audit-verify`, `nnpa-bench` join B's commands.
9. **`frontend/src/Live.tsx`** (new) and `App.tsx`. Adds the Live catalogue tab, decision card, operator actions, audit panel, decision evidence and platform evidence.
10. **Ops**. All runtime outputs go under `artifacts/` (the hardened unit only allows writes there). The bootstrap builds the sgp4 C extension. The pipeline adds the decision and catalogue stages. The Dockerfile is multi-stage.

## Dropped or parked

- A's Jinja dashboard (`src/app`). The React console replaces it. Its 3D debris-cloud snapshot code (`consequence/snapshot.py`) is kept for a later port.
- A's `scripts/get_data.py`, which downloaded the full archive including the private test labels. B's `fetch-data` keeps those labels sealed until a model is frozen.
- A's `models/` and `data/` directories. Everything now lives under `artifacts/`.

## Numbers that must be re-measured on LinuxONE

B's tables were measured on s390x before the merge. A's were mostly measured on Windows. The integrated screener (Pc gating, refined miss) and the decision-layer evaluation through the sealed path are new code, so run `bash scripts/run-linuxone-pipeline.sh` on the VM and quote those outputs in the video. Do not quote the development-machine numbers.
