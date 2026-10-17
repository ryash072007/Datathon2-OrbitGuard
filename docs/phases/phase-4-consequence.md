# Phase 4: Consequence engine ("what if it collides?")

## In one sentence
For a close approach, this phase estimates how much debris a crash would make and how many other satellites that debris would threaten over the next 30 days.

## Why it matters
Collision probability (Pc) says how likely a crash is. It does not say how bad the crash would be. A crash at a busy altitude can hurt far more satellites than a crash somewhere quiet. Two events with similar Pc can deserve very different attention. We rank by expected harm, which is Pc times expected encounters.

## How it works
Terms: **Pc** is the chance two objects collide. **TLE** is a public orbit description for one object. **J2** is the effect of Earth's bulge on an orbit. **Encounter** means a debris piece passes within 1 km of a satellite.

1. **Break the objects up.** NASA's Standard Breakup Model gives a power law for how many fragments of each size a crash makes. Masses are assumed by object type.
2. **Spread the cloud.** Each fragment's orbit is evolved analytically with J2. There is no drag.
3. **Build a density map.** Think of a weather map, but for debris. It has three axes (altitude, latitude, right ascension) and is built day by day for 30 days.
4. **Fly every active satellite through the map.** Expected encounters = density x relative speed x area x time. This is the kinetic-gas idea used in Kessler-syndrome studies: debris is like gas, and a satellite is a moving target in it.
5. **Compute harm.** Expected harm = Pc x total expected encounters.

Only 3,000 fragments are simulated. Each carries a weight so the totals still stand for the full count.

## Results
ISS (assumed 420 t) vs ENSHI XIDA SHANQUAN (assumed 500 kg payload):

| Quantity | Value |
| --- | --- |
| Miss distance / relative speed | 4.98 km / 7.6 km/s |
| Breakup class (NASA 40 J/g rule) | Non-catastrophic |
| Ejected mass | 28.5 t |
| Fragments of 10 cm or more | about 11,259 |
| Fragments that re-enter (perigee below 150 km) | 33.9% |
| Pc (isotropic 1 km TLE error, 20 m hard-body radius) | 8.3e-10 |
| Active LEO satellites with 1 or more expected passes within 1 km | 8,943 of 15,145 |
| Total expected encounters | 18,337 |
| Expected harm | 1.5e-5 |

Sanity checks:
- About 7,400 surviving fragments in a shell about 300 km thick give about 4e-8 per km3. Times 10 km/s, a 1 km radius disc and 30 days, that is about 1 to 3 encounters per satellite in the shell. This matches the tool.
- Iridium-Cosmos-like masses (about 2 t) give about 1.5k fragments of 10 cm or more. That is the right order of magnitude.

Survey of 20 random active LEO events (seed 0, 13 of 20 are Starlink, 36 s on 12 workers):

| Check | Result |
| --- | --- |
| Spearman rank correlation, Pc ranking vs harm ranking | 0.78 |
| Events that move 3 or more places | 11 of 20 |

Examples: STARLINK-30067 is 5th by Pc but 1st by harm. PRAETORIAN SDA_610 goes 12th to 4th. STARLINK-34170 goes 1st to 6th. "Good" here means the harm ranking differs from the Pc ranking in sensible ways. 24 tests pass.

## Try it
```
.venv/Scripts/python -m src.consequence.run --primary 25544
.venv/Scripts/python -m src.consequence.run --survey 20 --seed 0
```
Code is in [src/consequence/](../../src/consequence/). Key files: [breakup.py](../../src/consequence/breakup.py), [cloud.py](../../src/consequence/cloud.py), [exposure.py](../../src/consequence/exposure.py), [pc.py](../../src/consequence/pc.py), [run.py](../../src/consequence/run.py).

## Limits and honest caveats
- Masses are assumed by object type.
- Size range is 10 cm to 1 m, with a simplified area-to-mass distribution.
- No drag.
- The cloud is spread randomly along-track from day 1.
- No background-debris subtraction.
- "Encounter within 1 km" is not a collision.
- Pc comes from public TLEs with an assumed error.
- Use results for relative ranking, not absolute prediction.

## What's next
Phase 5 adds the super-spreader network, the LLM agent and the dashboard. Phase 6 ports everything to the LinuxONE VM.
