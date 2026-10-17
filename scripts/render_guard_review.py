"""Render the frozen escalation experiment without hand-entered metrics."""

import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('artifacts/review-linuxone/ml/guard_evidence.json'))
    parser.add_argument('--output', type=Path, default=Path('docs/RECALL_IMPROVEMENT.md'))
    options = parser.parse_args()
    report = json.loads(options.input.read_text())
    methods = report['methods']
    baseline, guard = methods['latest_baseline'], methods['residual_guard']
    nested = report['policy']['nested_validation']
    interval = report['paired_bootstrap']['loss_difference_ci95']
    names = {'latest_baseline': 'Latest-risk baseline', 'residual_guard': 'Baseline plus learned review', 'simple_threshold': 'Lower threshold only'}
    rows = [f"| {names[name]} | {value['recall']:.1%} | {value['precision']:.1%} | {value['fn']} | {value['fp']} | {value['challenge_loss']:.6f} |" for name, value in methods.items()]
    text = f"""# Reducing missed alerts

Generated from the frozen LinuxONE escalation evaluation by `scripts/render_guard_review.py`.
Evaluation time: {report['generated_at']}.

## Measured improvement and its cost

The supplemental learned review rule detects **{guard['tp']} of {guard['high_risk_event_count']} high-risk encounters**, compared with {baseline['tp']} for the baseline. Missed encounters decrease from **{baseline['fn']} to {guard['fn']}**, while false alarms increase from **{baseline['fp']} to {guard['fp']}**.

| Policy | Recall | Precision | Missed | False alarms | ESA loss |
|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

This is a small retrospective gain, not a general accuracy guarantee. The paired 95% loss-difference interval is **[{interval[0]:+.5f}, {interval[1]:+.5f}]**; it crosses zero, so a reliable loss improvement is not established. A simpler threshold alternative is reported alongside the learned rule rather than omitted.

## How the rule works

1. Preserve every baseline high-risk alert and its forecast.
2. For other encounters, compare the frozen residual-model forecast against a threshold selected using training-event out-of-fold predictions.
3. Flag additional qualifying events for operator review. A conditional training-only risk estimate is retained for evaluation, while the UI keeps the baseline forecast and labels the additional review as experimental.

Threshold: **{report['policy']['threshold']:.6f} log10 units**. It maximizes training-validation F2 subject to preserving baseline alerts and a false-positive budget of at most 25% above baseline. Ties prefer fewer false positives. The budget applies to development data, not future traffic.

No test labels select the threshold or conditional estimate. The base-model fingerprint, threshold, calibration value and source fingerprint are frozen before the released labels are loaded by this evaluation. The base model and manoeuvre planner are not replaced.

## What nested validation says

Threshold selection and the conditional estimate are refit inside each outer event fold, with an inner cross-validation loop for residual forecasts. Base-model hyperparameters come from the earlier development cycle, so this remains development evidence.

- Baseline: {nested['baseline']['fn']} missed, {nested['baseline']['fp']} false alarms, loss {nested['baseline']['challenge_loss']:.6f}.
- Learned review: {nested['guard']['fn']} missed, {nested['guard']['fp']} false alarms, loss {nested['guard']['challenge_loss']:.6f}.
- Lower threshold: {nested['simple_threshold']['fn']} missed, {nested['simple_threshold']['fp']} false alarms, loss {nested['simple_threshold']['challenge_loss']:.6f}.

Nested validation shows a weaker gain and worse loss, so this rule remains **experimental supplemental review**, not a replacement default forecast. It cannot suppress a baseline alert, but it can add false alarms.

The released test set was previously evaluated by earlier project versions. This is a retrospective recheck, not a new blind test. Further test-guided threshold tuning would invalidate claims of independent generalization.

## Reproduce

```bash
orbitguard train-guard
orbitguard evaluate-guard
python scripts/render_guard_review.py
```

The API exposes `supplemental_review` for a matching frozen policy. The Encounters page shows an experimental review notice only for additional alerts; Validation reports the complete comparison. Restart the service after installing source or model artifacts. The rule does not command spacecraft or alter simulated manoeuvre recommendations.

Frozen base model: `{report['fingerprints']['base_model']}`.
Frozen policy before labels: `{report['fingerprints']['policy_before_labels']}`.
Policy after evaluation: `{report['fingerprints']['policy_after']}`.

Context: the [ESA competition analysis](https://arxiv.org/html/2008.03069) discusses strong persistence baselines, class imbalance and threshold-based approaches. These experiment thresholds were selected from training validation; the published leaderboard is not a tuning set.
"""
    runtime_path = options.input.parent.parent / 'guard_runtime.json'
    test_path = options.input.parent.parent / 'guard-regression-tests.out'
    verification = None
    if runtime_path.exists() and test_path.exists():
        runtime = json.loads(runtime_path.read_text())
        test_log = test_path.read_text()
        passed = re.search(r'(\d+) passed', test_log)
        if not passed:
            raise ValueError('Passing guard regression evidence is required')
        text += f"\n## Verification\n\n{passed.group(1)} Python tests pass on {runtime['architecture']}. Including supplemental review, measured forecast p95 is {runtime['p95_ms']:.2f} ms across {runtime['count']} calls after {runtime['warmup']} warmups. Scope: {runtime['scope']}.\n"
        verification = {'regression_output': test_log, 'runtime': runtime}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(text)
    evidence = options.output.parent / 'evidence'
    evidence.mkdir(exist_ok=True)
    (evidence / 'guard-review.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    if verification:
        (evidence / 'guard-verification.json').write_text(json.dumps(verification, indent=2, allow_nan=False) + '\n')
    print(options.output)


if __name__ == '__main__':
    main()
