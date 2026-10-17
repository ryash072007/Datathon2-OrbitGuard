# Physics implementation worklog

Owner: physics subagent. This file is the durable handoff for the numerical simulator and planning subsystem.

## Current state

- Implemented independent 2D encounter-plane Gaussian disk integration, positive-definite covariance checks, and explicit errors for invalid calculations.
- Implemented SI two-body DOP853 propagation, tangential burns, sampled closest-approach bracketing and root refinement, with tighter verification for selected policies.
- Implemented 37 candidates, three uncertainty standard-deviation scales, no-action/original-pair/all-object policy comparison, explicit abstention, and finite JSON output.
- Implemented four interactive synthetic scenarios, deliberate secondary-encounter construction, and deterministic 50-scenario stress suite.
- Implemented PhysicsService, CLI, NASA fixtures, validation, policy benchmark and runtime artifacts.
- Added primary and secondary local views for the interface: X along-track, Y cross-track, Z radial, relative to nominal A. Full trajectories remain ECI in metres.

## Files

`orbitguard/physics/` owns risk/orbits/scenarios/planner/service/validation/cli modules and pinned fixtures. `tests/test_physics.py` owns subsystem checks. Generated real evidence is under `artifacts/physics/`.

## Commands

```bash
.venv/bin/python -m pytest tests/test_physics.py -q
.venv/bin/python -m orbitguard.physics.cli validate-physics --root .
.venv/bin/python -m orbitguard.physics.cli benchmark-planner --root . --count 50 --runtime-repetitions 20
```

Coordinator CLI may delegate the same command names to `orbitguard.physics.cli.main([command, ...args])`. `ORBITGUARD_ROOT` sets the default artifact root.

## Measured checks so far

- All three NASA reference cases pass required relative tolerance 0.001. Omitron error 2.88e-6; Alfano01 error 3.30e-7; Alfano02 error 8.92e-9.
- Analytic Gaussian, rotation, object swap, radius monotonicity, invalid covariance rejection and propagation conservation checks pass.
- Local arm64 illustrative scenario: primary-only uses -0.05 m/s and creates secondary Pc ~0.02148; all-object screening selects +0.05 m/s, primary worst Pc ~4.77e-5 and secondary ~7.15e-9. These are synthetic scenario outcomes, not observed satellite data.
- Initial measured full screening duration is approximately 0.7 seconds locally including tighter verification. No LinuxONE timing claim yet.

## Completed local evaluation

- `13 passed` in `tests/test_physics.py`.
- All 50 fixed scenarios evaluated with no failed scenario. No action: 10 acceptable outcomes. Original-pair policy: 20 acceptable, 20 introduced secondary hazards, 10 correct abstentions. OrbitGuard: 40 acceptable, zero introduced secondary hazards or unsafe selections, 10 correct abstentions.
- Both active policies have the same mean absolute delta-v of 0.0375 m/s across their 40 non-abstaining cases (clear cases included).
- Introduced hazards require the selected policy to violate the threshold while no action remains below it for secondary objects, using the maximum across all three uncertainty settings.
- Twenty uncached serial screening runs after one warm-up: local arm64 p50 695.7 ms, p95 728.2 ms. These are local measurements, not LinuxONE timings.
- Generated `validation.json`, `benchmark.json`, `scenario_suite.json`, `demonstration.json`, `runtime.json`, and one per-scenario result under `artifacts/physics/runs/`.
- A trajectory-rendering empty-mask defect was found by the integration-oriented unit test and fixed; no probability or benchmark result was affected.

## Important boundaries

- Secondary stress cases deliberately put C on the original-pair-selected path. The suite composition and construction are disclosed; rates do not estimate real-world event frequency.
- All displayed collision risks are maxima over the three tested uncertainty scales. This is a finite sensitivity check, not a guarantee.
- Partial encounters at horizon boundaries and slow co-orbital encounters are unsupported. Fixture encounters are interior and fast.
- Local RTN uncertainty is prescribed at each encounter rather than propagated orbit-determination covariance.
- Missing numerical evidence remains explicitly missing; service construction never invents results.

## Next integration steps

1. Coordinator runs validation and benchmark on LinuxONE using the same source and pinned dependencies.
2. Confirm UI renders primary/secondary local views and all abstention states.
3. Final independent code review should check policy selection, horizon/uncertainty disclosures, and runtime provenance.
4. Root owns a serial versus bounded-parallel **scenario job** comparison. Candidate screening remains serial: no nested process pool or unsupported candidate-level speedup claim.
