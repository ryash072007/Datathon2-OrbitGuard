# Satellite Collision Avoidance (IBM Z Datathon 2026)

Decision-support tool that ranks which satellite close approaches are truly risky and screens candidate
avoidance manoeuvres in parallel on IBM LinuxONE (s390x). A human operator stays in the loop.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/VM: .venv/bin/python
python scripts/get_data.py                                 # downloads ESA dataset into data/raw/cac/
```

## Phase 1: risk model

```bash
python -m src.risk.train       # trains models/risk_hgb.joblib (retrain on each machine, never copy)
python -m src.risk.evaluate    # naive vs model on the ESA test set -> models/risk_metrics.json
python -m pytest tests -q
```

## Phase 2: decision layer

```bash
python -m src.risk.decision fit    # learns rules/gate by GroupKFold CV on train -> models/decision.joblib
python -m src.risk.decision eval   # naive vs chosen candidate on test (once), interval coverage, example Decision
```

`predict_risk` uses `models/decision.joblib` when present (else the naive latest-CDM risk);
`src.risk.decision.decide(cdms)` returns action (ACT/WAIT/MONITOR), P(high), 80% interval and reasons.

## Phase 3: manoeuvre screener

```bash
python -m src.screen.run --primary 25544 --days 3 --target-km 2          # find closest approach, screen 145 burns, write data/out/screen_*.csv/json
python -m src.screen.run --primary 25544 --days 3 --benchmark            # also writes data/out/speedup_<host>.json (1,2,4..cpu_count workers)
python -m src.screen.run --primary 25544 --threat 12345 --workers 8      # force the threat; WORKERS env var sets the default
python -m pytest tests -q
```

Downloads CelesTrak TLEs to `data/raw/celestrak/` (cached 6 h). The catalogue ephemeris is a `<f8` memmap in `data/cache/`
(regenerated on each machine, never copied).

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
