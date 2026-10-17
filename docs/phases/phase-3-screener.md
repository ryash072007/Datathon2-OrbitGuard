# Phase 3: Cascade-aware manoeuvre screener

## In one sentence
Given a risky close approach, we test 145 candidate burns in parallel and rank them by fuel cost and by whether they create new close calls.

## Why it matters
Moving a satellite away from one object can push it toward another. A good burn must widen the miss distance, use little fuel and not start a new problem. Checking this by hand against thousands of objects is slow.

## How it works
1. **Find the threat.** Use public orbit data (TLEs from CelesTrak: a TLE is a short text description of an orbit). Search for the closest approach between the primary (the ISS, NORAD 25544) and the catalogue. TCA is the time of closest approach.
2. **Prefilter.** Drop objects whose altitude range cannot meet ours (within 50 km). 6,762 objects remain.
3. **Build candidate burns.** Six directions (radial, along-track, cross-track, each plus or minus), several sizes and several lead times. Fuel is measured as delta-v, the speed change of the burn in m/s. See [burns.py](../../orbitguard/catalog/burns.py).
4. **Delta propagation.** SGP4 (the standard orbit predictor for TLEs) cannot model a burn. A simple physics model could, but it disagrees with SGP4 by kilometres, which would hide a tiny burn. So we run the simple model twice: once without the burn, once with it. Only the difference is added to the SGP4 path. Shared errors cancel. Analogy: weigh a bag with and without an apple, and trust the difference even if the scale is slightly off. A zero burn reproduces SGP4 exactly. See [propagate.py](../../orbitguard/catalog/propagate.py).
5. **Coarse then fine screening.** First check every object once a minute and flag only those that could possibly come close. Then recheck flagged windows every second. Analogy: skim a long video, then replay only the interesting scenes. See [screen.py](../../orbitguard/catalog/screen.py).
6. **Score and rank.** Score is delta-v plus a penalty for each new close approach (under 5 km) that the no-burn path did not have. The penalty is scaled by a criticality proxy. Burns that meet the target miss distance rank first. Work is split across CPU cores ([parallel.py](../../orbitguard/catalog/parallel.py)).

## Results
Run: ISS vs ENSHI XIDA SHANQUAN (NORAD 64962), TCA 2026-10-18 04:48:38 UTC. Baseline miss 4.98 km. Target miss 10 km.

| Item | Value |
| --- | --- |
| Best burn | +T (prograde) 0.5 m/s, 3 orbits before TCA |
| Miss after best burn | 22.3 km, 0 new conjunctions |
| -T 0.5 m/s, 3 orbits | 22.0 km, but 1 new close approach, so it ranks lower |
| Burns meeting 10 km | 4 of 144, all along-track |
| Physics check | 0.5 m/s drifts about 8 km per orbit; expect about 16 km (2 orbits) and 25 km (3). Tool: 15.3 and 22.3 km |
| Total time | 12.9 s (closest-approach search 6.4 s, 145 burns on 12 workers 6.1 s) |

Parallel speed-up on a 12-core Windows PC (1 worker: 29.8 s):

| Workers | Speed-up |
| --- | --- |
| 2 | 1.65x |
| 4 | 2.81x |
| 8 | 4.38x |
| 12 | 4.84x |

Good means: the miss grows past the target, no new conjunctions, low delta-v, and the physics check roughly agrees.

## Try it
```
.venv/Scripts/python -m orbitguard.catalog.run --primary 25544 --days 3 --target-km 10
.venv/Scripts/python -m orbitguard.catalog.run --primary 25544 --days 3 --target-km 10 --benchmark
```

## Limits and honest caveats
- TLEs carry about 1 km of position error and no covariance. This is decision support, not operational.
- The delta model uses J2 only and ignores drag.
- Criticality is a shell-density proxy, because we have no mass data.
- New conjunctions are matched per object.
- We used a 10 km target because the 2 km default was already met with no burn.
- Scaling is limited by memory bandwidth. LinuxONE numbers come in Phase 6.

## What's next
Phase 4 adds a consequence engine: what happens if the pair does collide.
