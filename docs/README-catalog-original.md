# [Datathon2_IBM Z Datathon 2026 Project]: Cascade-aware satellite collision avoidance on IBM LinuxONE

> Probability tells you how likely. We tell you what it would cost, and which dodge doesn't start a cascade.

**Theme: Real-Time AI for Critical Decisions.** This is decision support. A human operator makes every call.

## The problem

Operators receive a stream of close-approach warnings (CDMs). Most fade away and a few are real. In the ESA
dataset, only 66 of 8,293 usable training events end at high risk, and in the 2019 challenge only 12 of 97 teams
beat the naive "copy the latest message" baseline. A collision probability also says nothing about how bad a crash
would be, or whether the avoidance burn pushes the satellite toward another object. Our catalogue sweep covers
about 17k objects, so a dodge can easily create a new conflict.

## What it does

1. [**Act / Wait / Monitor**](docs/phases/phase-2-decision-layer.md): a recommendation with a calibrated probability, an 80% interval and reasons.
2. [**Cascade-aware screener**](docs/phases/phase-3-screener.md): tests 145 candidate burns in parallel and ranks them by delta-v and new close approaches.
3. [**Consequence engine**](docs/phases/phase-4-consequence.md): breakup, 30-day debris cloud, expected encounters and expected harm.
4. [**Super-spreader network**](docs/phases/phase-5-network-brief-dashboard.md): catalogue-wide close-approach graph that flags objects able to seed a chain reaction.
5. [**Granite brief with grounding guard**](docs/phases/phase-5-network-brief-dashboard.md): IBM Granite writes the operator brief on the box. Any number not in the facts triggers a template fallback.
6. [**Tamper-evident audit log**](orbitguard/audit/README.md): hash-chained record of briefs, screens and operator decisions (`python -m orbitguard.audit verify`).

All of it is in one Flask dashboard ([Phase 5](docs/phases/phase-5-network-brief-dashboard.md)), including a 3D
debris-cloud globe and a real-time decision replay. Phase notes are indexed in [docs/phases](docs/phases/README.md).

## Architecture

![Architecture flowchart](docs/architecture.svg)

Details: [docs/architecture.md](docs/architecture.md).

## Results

| Item | Result | Source |
| --- | --- | --- |
| Decision layer, L (lower is better) | 0.680 vs naive 0.694 | [Phase 2](docs/phases/phase-2-decision-layer.md) |
| ISS burn | Miss 4.98 to 22.3 km with 0 new conjunctions; the alternative burn creates 1 | [Phase 3](docs/phases/phase-3-screener.md) |
| Screener speed-up | 4.8x on 12 cores (Windows; LinuxONE numbers in `docs/evidence/`) | [Phase 3](docs/phases/phase-3-screener.md) |
| Consequence, ISS event | About 11k fragments; 8,943 satellites with 1 or more expected passes within 1 km | [Phase 4](docs/phases/phase-4-consequence.md) |
| Harm vs probability ranking | Spearman 0.78; 11 of 20 events move 3 or more places | [Phase 4](docs/phases/phase-4-consequence.md) |
| Breakup validation (predicted / catalogued) | Iridium-Cosmos 0.51, Fengyun-1C 0.35, Cosmos 1408 0.77 | [validation](docs/validation.md) |
| Network | 179,075 encounters in 24 h; sweep 16 s | [Phase 5](docs/phases/phase-5-network-brief-dashboard.md) |
| Granite brief | About 20 s per brief; grounded 3 of 3 | [Phase 5](docs/phases/phase-5-network-brief-dashboard.md) |

These numbers were measured on a Windows PC (12 cores), not on LinuxONE.

## Why IBM LinuxONE

- **Parallel screening.** Burns and the catalogue sweep split across all cores. The screener scaled 4.8x on 12 cores on Windows. The LinuxONE benchmark is the planned measurement.
- **Compute.** The screener, consequence engine and network sweep are CPU-heavy and run on the same box.
- **On-box LLM.** Granite 3.3 2B runs through llama.cpp, using a big-endian GGUF converted for s390x ([porting](docs/porting.md)).
- **Containerised.** One [Dockerfile](Dockerfile) builds on the official s390x image.
- **Data stays on premises.** No external AI API is needed. Only the public TLE and SATCAT downloads come in.
- **Audit log.** It pairs with IBM Z hardware-backed integrity (pervasive encryption, Secure Execution). That is a design note, not something we have run.

Measured vs planned: the code, tests and all results above ran on Windows in a venv pinned to the VM image
versions. The dashboard, Granite and the benchmark are not yet confirmed on the VM. Evidence from the VM
(`lscpu`, htop, benchmark, `docker ps`, screenshots) goes in [docs/evidence/](docs/evidence/) following the
[VM runbook](docs/vm_runbook.md). If that folder is empty, that run has not happened yet.

## Quick start

### Windows or Linux

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/VM: .venv/bin/python
python scripts/get_data.py                                 # downloads ESA dataset into data/raw/cac/
python scripts/demo.py                                     # prepares everything and starts the dashboard
```

Open http://localhost:8080. Use `python scripts/demo.py --quick` to skip the survey and network sweep, `--no-serve`
to prepare only, `--llm` to use Granite. Tests: `python -m pytest tests -q`.

### LinuxONE VM

Follow [docs/vm_runbook.md](docs/vm_runbook.md): setup, tests, demo prep, Granite conversion, benchmark, container, evidence.

### Docker

```bash
docker build -t datathon2 .
docker run -d --name datathon2 -p 8080:8080 -v $PWD/data:/app/data -v $PWD/models:/app/models datathon2
```

The default base is the official s390x image. On x86 add `--build-arg BASE=python:3.12-slim`.

### Commands by phase

Phase 1, risk model:

```bash
python -m orbitguard.decision.train       # trains models/risk_hgb.joblib (retrain on each machine, never copy)
python -m orbitguard.decision.evaluate    # naive vs model on the ESA test set -> models/risk_metrics.json
python -m pytest tests -q
```

Phase 2, decision layer:

```bash
python -m orbitguard.decision.decision fit    # learns rules/gate by GroupKFold CV on train -> models/decision.joblib
python -m orbitguard.decision.decision eval   # naive vs chosen candidate on test (once), interval coverage, example Decision
```

`predict_risk` uses `models/decision.joblib` when present (else the naive latest-CDM risk);
`orbitguard.decision.decision.decide(cdms)` returns action (ACT/WAIT/MONITOR), P(high), 80% interval and reasons.

Phase 3, manoeuvre screener:

```bash
python -m orbitguard.catalog.run --primary 25544 --days 3 --target-km 2          # find closest approach, screen 145 burns, write data/out/screen_*.csv/json
python -m orbitguard.catalog.run --primary 25544 --days 3 --benchmark            # also writes data/out/speedup_<host>.json (1,2,4..cpu_count workers)
python -m orbitguard.catalog.run --primary 25544 --threat 12345 --workers 8      # force the threat; WORKERS env var sets the default
python -m pytest tests -q
```

Downloads CelesTrak TLEs to `data/raw/celestrak/` (cached 6 h). The catalogue ephemeris is a `<f8` memmap in `data/cache/`
(regenerated on each machine, never copied).

Phase 4, consequence engine:

```bash
python -m orbitguard.consequence.run --primary 25544            # breakup -> debris cloud -> exposed satellites -> expected harm
python -m orbitguard.consequence.run --survey 20 --seed 0       # Pc ranking vs expected-harm ranking, Spearman rho
python -m orbitguard.consequence.validate                       # breakup model vs real events (docs/validation.md)
```

Masses are rough assumptions (`orbitguard/consequence/objects.py`); outputs go to `data/out/`.

Phase 5, network, grounded brief, dashboard, audit:

```bash
python -m orbitguard.network.run --hours 24                     # catalogue-wide close-approach graph, top super-spreaders
python -m orbitguard.brief.run --primary 25544 --cdm-event 8    # facts -> brief; LLM_BACKEND=template|llamacpp|openai
python -m legacy.flask_dashboard.run                                    # Flask dashboard on 0.0.0.0:$PORT (default 8080)
python -m orbitguard.audit verify                               # check the audit hash chain
```

LLM backends: `LLM_BACKEND=llamacpp` with `LLM_MODEL_PATH` (GGUF), or `openai` with `LLM_BASE_URL`, `LLM_MODEL`,
optional `LLM_API_KEY`. Any number in LLM output that is not in the facts triggers a fall back to the template.

Local Granite test on Windows (little-endian GGUF; the VM needs a big-endian conversion, see [docs/porting.md](docs/porting.md)):

```bash
.venv/Scripts/python -m pip install llama-cpp-python --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
# download granite-3.3-2b-instruct-Q4_K_M.gguf from ibm-granite/granite-3.3-2b-instruct-GGUF into models/llm/
LLM_BACKEND=llamacpp LLM_MODEL_PATH=models/llm/granite-3.3-2b-instruct-Q4_K_M.gguf python -m orbitguard.brief.run --primary 25544
```

The dashboard brief panel reports the backend used and a grounded badge through the same `make_brief_from_facts` API.

## Limitations

- TLEs carry about 1 km of position error and come without covariance. This is decision support, not operational.
- Masses are assumed by object type, so consequence and super-spreader scores are a ranking aid, not a measurement.
- The consequence model under-predicts fragment counts: predicted/catalogued ratios are 0.35 to 0.77 ([validation](docs/validation.md)). Use it for relative ranking.
- The decision layer was tested on historical CDMs only. Its gain over naive is small (F2 is slightly lower) and the 80% interval is very wide.
- Gradient-boosting models did not beat naive (best L 0.706 vs 0.694). We report that as a negative result.
- Granite sometimes numbers list items and phrases uncertainty loosely. The guard checks numbers, not wording.
- The burn model uses J2 only and ignores drag. The consequence model also ignores drag.

## Repo layout

```
orbitguard/decision/         risk baseline and decision layer
orbitguard/catalog/       cascade-aware manoeuvre screener
orbitguard/consequence/  breakup, debris cloud, expected harm, validation
orbitguard/network/      super-spreader network
orbitguard/brief/        facts, Granite backends, grounding guard, template
orbitguard/audit/        hash-chained audit log
legacy/flask_dashboard/          Flask dashboard
scripts/          get_data, demo, VM setup, Granite conversion, evidence
docs/             architecture, phase notes, validation, porting, VM runbook, video script
tests/            smoke tests
```

## Credits

- ESA Collision Avoidance Challenge dataset: https://zenodo.org/records/4463683 and https://kelvins.esa.int/collision-avoidance-challenge/
- Uriot et al., "Spacecraft collision avoidance challenge": https://arxiv.org/abs/2008.03069
- NumPy: https://numpy.org
- pandas: https://pandas.pydata.org
- scikit-learn: https://scikit-learn.org
- SciPy: https://scipy.org
- joblib: https://joblib.readthedocs.io
- CelesTrak (TLE catalogue): https://celestrak.org
- sgp4 Python library: https://pypi.org/project/sgp4/
- Vallado, Crawford, Hujsak, Kelso, "Revisiting Spacetrack Report #3": https://celestrak.org/publications/AIAA/2006-6753/
- Bombardelli group, along-track manoeuvre optimality: https://oa.upm.es/51461/
- Johnson et al., "NASA's new breakup model of EVOLVE 4.0" (2001): https://doi.org/10.1016/S0273-1177(01)00423-9
- Flask: https://flask.palletsprojects.com
- pytest: https://pytest.org
- llama.cpp: https://github.com/ggml-org/llama.cpp (s390x build notes: https://github.com/ggml-org/llama.cpp/blob/master/docs/build-s390x.md)
- llama-cpp-python: https://github.com/abetlen/llama-cpp-python
- IBM Granite 3.3 2B Instruct: https://huggingface.co/ibm-granite/granite-3.3-2b-instruct and its GGUF: https://huggingface.co/ibm-granite/granite-3.3-2b-instruct-GGUF
