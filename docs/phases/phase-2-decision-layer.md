# Phase 2: Act / Wait / Monitor decision layer

## In one sentence
For each event we give a recommendation (Act, Wait or Monitor), a probability, an interval and plain-English reasons.

## Why it matters
A single risk number is hard to act on. Operators need a clear next step and the reasons behind it. This is decision support: a human decides.

## How it works
1. **Start from naive.** Take the latest CDM's risk.
2. **Two rules.** Risks in [-6.04, -6) are promoted to -5.95, because they often cross the line. Risk is forced low when the other object is a payload (a working satellite) or the miss distance is over 15 km.
3. **Learned safely.** The rule thresholds were chosen by cross-validation on training data only.
4. **Probability and interval.** A calibrated probability that the final risk ends at -6 or above, plus an 80% interval.
5. **Decision.** Thresholds on that probability give ACT, WAIT or MONITOR, with reasons. See [decision.py](../../orbitguard/decision/decision.py).

## Results (test set, 2,167 events)
| Metric | Naive | Rules (A) |
| --- | --- | --- |
| L (lower is better) | 0.694 | 0.680 |
| F2 | 0.739 | 0.736 |
| Precision | 0.646 | 0.673 |

The 80% interval covers 88% of true values, but is very wide (mean 9.7 log units).

## Try it
```
.venv/Scripts/python -m orbitguard.decision.decision eval
```

## Limits and honest caveats
- The gain over naive is small, and F2 is slightly lower.
- The interval is honest but too wide to be precise.
- Only a decision aid; it does not choose manoeuvres yet.

## What's next
Phase 3 onwards: see the [index](README.md).
