# ML implementation handoff

## Current state

- Own modules: `orbitguard/ml/{data,model,service,cli}.py`; meaningful checks in `tests/test_ml.py`.
- Official ESA train archive, public test CSV, and compressed Zenodo released-label member downloaded into ignored `artifacts/ml/data`.
- Selected members verified against official ZIP central-directory CRC32 and sizes; SHA256 recorded in `artifacts/ml/provenance.json`. Full 221MB archive MD5 is a reference only, not claimed verified.
- Final labels remain compressed and unread. `read_labels()` requires frozen model files and reads only `event_id,true_risk`.
- Training running locally with bounded threads; frozen model must precede final evaluation.

## Discoveries and validated dataset counts

ESA event IDs are independently numbered inside train and test source files. Training has IDs 0–13153, test 0–2166. Raw numeric overlap is 2167, so a naive intersection test would incorrectly reject the official split. Namespace events as train:<id>/test:<id>. Confirmed zero exact duplicate CDM rows across splits after excluding event_id. Official source describes each dataset as its own event collection: https://kelvins.esa.int/collision-avoidance-challenge/data/ .

- Train: 162634 rows, 13154 events.
- Eligible training: 8293 events, including 66 final high-risk encounters; 4861 excluded for lacking >=2-day inputs or <=1-day target.
- Test: 24484 input rows, 2167 events; every input satisfies >=2-day cutoff.
- Target is final reported log10 risk, never observed physical collision.

## Reproduction commands

```sh
.venv/bin/python -m orbitguard.ml.cli fetch-data
.venv/bin/python -m orbitguard.ml.cli prepare-data
.venv/bin/python -m orbitguard.ml.cli train
.venv/bin/python -m orbitguard.ml.cli evaluate
.venv/bin/python -m pytest tests/test_ml.py -q
```

All CLI commands accept `--root` and use `ORBITGUARD_ROOT` if set. Data acquisition invokes system curl for macOS certificate compatibility. Linux uses the installed curl. Scientific stack is coordinator-provided NumPy, SciPy, pandas, sklearn, joblib, threadpoolctl.

## Public service shapes

`MLService(root)` provides list_events, get_event, forecast, evidence per CONTRACTS.md. Event detail includes eligible `history` and `messages` aliases, a forecast object, and a retrospectively labelled `reference` from evaluated prediction artifacts. The service never opens private label files. Evidence contains `metrics` rows, `model`, `dataset`, `validation`, `runtime`, `precision_recall_curve`, and `limitations`. Missing artifacts yield explicit missing evidence or descriptive errors.

## Next steps

1. Complete bounded training CV and model freeze.
2. Run evaluation once against released labels, including baseline reproduction (~0.694), 1000 paired bootstrap samples, learned-vs-baseline and actual platform evidence.
3. Share results and rerun evaluation/training on LinuxONE under coordinator control.
4. Independent reviewer checks leakage, score implementation, artifact traceability.

## Completed local evaluation — actual results

Training and model selection completed with 16 bounded configurations and three event-level folds. The default correctly remains latest-risk baseline because no learned trial met the improvement rule. Learned challenger remains available as `learned_forecast_log10_pc` in forecast output.

Final held-out test: 2167 encounters, 150 high-risk references. Released labels were first read only after writing frozen model files. Before/after model SHA256 is `5ccaf5c8884eee52593f3426ad3f104aca0f7f6e4a03ee66c42d212024b67140`.

| Method | ESA loss (lower better) | F2 | Recall | Raw ranking AP |
|---|---:|---:|---:|---:|
| Latest-risk baseline | 0.693961261 (benchmark clipped) | 0.739075 | 0.766667 | 0.665077 |
| Learned residual challenger | 2.366947805 (benchmark clipped) | 0.419118 | 0.38 | 0.701367 |

Published rounded baseline ~0.694 reproduced. Learned point forecasts do **not** improve the baseline. Do not pitch superior risk prediction. Experimental raw ranking shows higher AP on this test, but confidence intervals must accompany any ranking-improvement claim. Never compare learned raw AP against baseline clipped AP, since clipping destroys useful ranking information.

1000 paired bootstrap samples give scored loss difference (learned minus baseline) 95% CI `[1.144369, 2.306617]`; this favours the baseline. LinuxONE still requires its own retraining/evaluation; these local measurements identify `macOS arm64` honestly. Core learned inference p95 ~1.8 ms locally, not API end-to-end timing.

Seven meaningful ML tests pass, including strict final-target `<1 day` eligibility, future-cutoff rejection, labels excluded from inference, no event-ID features, order-invariant aggregation, score calculation, and model-freeze guard.

Missing model/data now raises FileNotFoundError, allowing root API503. Final-target boundary changed from <=1 to <1 after verifying exactly0 real final CDMs at exactly1 day; training cohort unchanged. All data transfers are closed and ready for LinuxONE copy.
