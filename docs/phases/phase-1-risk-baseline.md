# Phase 1: Data and risk baseline

## In one sentence
We load real satellite close-approach data and measure how well anyone can predict the final collision risk.

## Why it matters
Operators get a stream of warnings about close passes. Most fade away; a few are real. Knowing early which is which saves fuel and avoids needless manoeuvres.

## How it works
1. **Data.** The ESA Collision Avoidance Challenge dataset: real, anonymised conjunction data messages (**CDMs**), 2015-2019. A CDM is one warning update about a close pass. Each event is a series of CDMs.
2. **Task.** Using only CDMs received at least 2 days before the closest approach (**TCA**), predict the final risk. Risk is the **log10 of the collision probability (Pc)**; -6 means a 1-in-a-million chance. "High risk" means -6 or above.
3. **Counts.** 13,154 training events, 8,293 usable under challenge rules, only 66 of them high-risk. The test set has 2,167 events, 150 high-risk.
4. **Metric.** L = mean squared error on high-risk events divided by **F2**. F2 is a score that rewards catching real threats (recall) more than avoiding false alarms. Lower L is better.
5. **Baselines.** "Naive" copies the latest CDM's risk as the forecast. We also trained gradient-boosting models.

## Results
| Method | L (lower is better) |
| --- | --- |
| Naive (latest message) | 0.694 |
| Best gradient boosting | 0.706 |

The models did not beat naive. This matches the 2019 challenge, where only 12 of 97 teams beat naive.

## Try it
```
.venv/Scripts/python scripts/get_data.py
.venv/Scripts/python -m orbitguard.decision.evaluate
```

## Limits and honest caveats
- Only 66 high-risk training events: too few for models to learn from.
- The result is a negative one for ML, and we report it as such.

## What's next
[Phase 2](phase-2-decision-layer.md): a rule-based decision layer that does beat naive.
