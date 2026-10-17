# Validation of the break-up model against real events

We run our simplified NASA Standard Breakup Model (`src/consequence/breakup.py`, N = 0.1 M^0.75 Lc^-1.71 for
Lc >= 10 cm) on three historical break-ups and compare the predicted fragment count with the number of debris
objects in the CelesTrak SATCAT for the same launch (international designator prefix, OBJECT_TYPE = DEB,
including objects that have since decayed). Reproduce with `python -m src.consequence.validate`.

| Event | Predicted >=10 cm | Catalogued debris (all-time) | Still on orbit | Ratio pred/cat |
|---|---|---|---|---|
| Iridium 33 / Cosmos 2251 (2009-02-10) | 1211 | 2372 | 725 | 0.51 |
| Fengyun-1C ASAT (2007-01-11) | 1224 | 3534 | 2314 | 0.35 |
| Cosmos 1408 ASAT (2021-11-15) | 1388 | 1806 | 4 | 0.77 |

Inputs (all masses approximate, from public reporting, not authoritative):

- **Iridium 33 / Cosmos 2251 (2009-02-10)**: Iridium 33 ~560 kg (689 kg quoted by some sources; 560 used) + Cosmos 2251 ~900 kg, ~11.7 km/s; SBM ejected mass M = 1460 kg.
- **Fengyun-1C ASAT (2007-01-11)**: target ~880 kg + kill vehicle ~600 kg (uncertain), ~9 km/s; SBM ejected mass M = 1480 kg.
- **Cosmos 1408 ASAT (2021-11-15)**: target ~1750 kg; interceptor mass unknown, treated as catastrophic with M = target mass; SBM ejected mass M = 1750 kg.

## How to read this

- Order of magnitude is what matters. The public catalogue tracks only roughly >= 10 cm objects (less reliably
  at high altitude), detection is incomplete, and small or short-lived fragments may never be catalogued. The
  catalogued count is therefore a lower bound on true >= 10 cm fragments, not a precise target.
- The designator prefix can also include debris from other pieces of the same launch, and for Iridium/Cosmos
  both parents are pooled, so counts are approximate in both directions.
- Interceptor masses and the Cosmos 1408 treatment are assumptions. We do not claim accurate per-event
  prediction, only that the model is not off by orders of magnitude.
- Source data: CelesTrak SATCAT, fetched 2026-10-17.
