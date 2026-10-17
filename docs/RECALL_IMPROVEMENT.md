# Reducing missed alerts

Generated from the frozen LinuxONE escalation evaluation by `scripts/render_guard_review.py`.
Evaluation time: 2026-10-17T11:17:31.254224+00:00.

## Measured improvement and its cost

The supplemental learned review rule detects **117 of 150 high-risk encounters**, compared with 115 for the baseline. Missed encounters decrease from **35 to 33**, while false alarms increase from **63 to 64**.

| Policy | Recall | Precision | Missed | False alarms | ESA loss |
|---|---:|---:|---:|---:|---:|
| Latest-risk baseline | 76.7% | 64.6% | 35 | 63 | 0.693961 |
| Baseline plus learned review | 78.0% | 64.6% | 33 | 64 | 0.682760 |
| Lower threshold only | 78.7% | 64.1% | 32 | 66 | 0.682162 |

This is a small retrospective gain, not a general accuracy guarantee. The paired 95% loss-difference interval is **[-0.03743, +0.00185]**; it crosses zero, so a reliable loss improvement is not established. A simpler threshold alternative is reported alongside the learned rule rather than omitted.

## How the rule works

1. Preserve every baseline high-risk alert and its forecast.
2. For other encounters, compare the frozen residual-model forecast against a threshold selected using training-event out-of-fold predictions.
3. Flag additional qualifying events for operator review. A conditional training-only risk estimate is retained for evaluation, while the UI keeps the baseline forecast and labels the additional review as experimental.

Threshold: **-6.576361 log10 units**. It maximizes training-validation F2 subject to preserving baseline alerts and a false-positive budget of at most 25% above baseline. Ties prefer fewer false positives. The budget applies to development data, not future traffic.

No test labels select the threshold or conditional estimate. The base-model fingerprint, threshold, calibration value and source fingerprint are frozen before the released labels are loaded by this evaluation. The base model and manoeuvre planner are not replaced.

## What nested validation says

Threshold selection and the conditional estimate are refit inside each outer event fold, with an inner cross-validation loop for residual forecasts. Base-model hyperparameters come from the earlier development cycle, so this remains development evidence.

- Baseline: 19 missed, 261 false alarms, loss 0.803753.
- Learned review: 18 missed, 273 false alarms, loss 0.826601.
- Lower threshold: 17 missed, 268 false alarms, loss 0.807449.

Nested validation shows a weaker gain and worse loss, so this rule remains **experimental supplemental review**, not a replacement default forecast. It cannot suppress a baseline alert, but it can add false alarms.

The released test set was previously evaluated by earlier project versions. This is a retrospective recheck, not a new blind test. Further test-guided threshold tuning would invalidate claims of independent generalization.

## Reproduce

```bash
orbitguard train-guard
orbitguard evaluate-guard
python scripts/render_guard_review.py
```

The API exposes `supplemental_review` for a matching frozen policy. The Encounters page shows an experimental review notice only for additional alerts; Validation reports the complete comparison. Restart the service after installing source or model artifacts. The rule does not command spacecraft or alter simulated manoeuvre recommendations.

Frozen base model: `9da3561c69b4efe2ac088e74e6102106cbcdd78dfad57c50d463b68f0a836fb9`.
Frozen policy before labels: `555248c9b29e3f8abbf5e501790e49a653797616b5a9f3add605fe5989d522eb`.
Policy after evaluation: `555248c9b29e3f8abbf5e501790e49a653797616b5a9f3add605fe5989d522eb`.

Context: the [ESA competition analysis](https://arxiv.org/html/2008.03069) discusses strong persistence baselines, class imbalance and threshold-based approaches. These experiment thresholds were selected from training validation; the published leaderboard is not a tuning set.

## Verification

50 Python tests pass on s390x. Including supplemental review, measured forecast p95 is 8.62 ms across 100 calls after 20 warmups. Scope: Forecast service calls including supplemental review; three escalated historical events; network excluded.
