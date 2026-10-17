# OrbitGuard implementation plan

## Product and evidence

An operator console forecasts final ESA collision-risk estimates from CDMs available >=48h before TCA, and separately demonstrates secondary-hazard-aware manoeuvre planning in a clearly synthetic orbital neighbourhood. Three screens: Encounter Monitor, Manoeuvre Lab, Evidence. All displayed metrics must come from generated artifacts.

Success: reproducible held-out comparison with latest-risk/ESA-clipped/constant baselines; independent NASA probability checks; no_action vs pair_only vs all-object planner on a predefined synthetic suite; actual LinuxONE model training/inference/screening; a clear <=3-minute demo and shareable source repository.

## Model

Use official train/test event split, with three-fold stratified train-only CV seed42. Inputs time_to_tca>=2; target latest CDM within final day. One example/event. Features: latest numeric attributes, object type, history counts/span, risk/miss-distance/uncertainty trends; exclude event/mission IDs. Histogram gradient boosting predicts correction to latest log risk; blend alpha0,.25,.5,1. Bounded 16-config search. Floor fitting log risk at -12; preserve original labels for evaluation. Private file loads only event_id and true_risk, after configuration freeze.

Metrics: challenge high-risk MSE/F2, precision/recall/F2 and confusion counts, average precision, PR curve, high-risk log RMSE, top10% recall. Reproduce published ~0.694 clipped-latest baseline. Report honest results even if ML loses. Include train-only feature ablation and event-bootstrap intervals. Target10% loss reduction is aspirational, never fabricated.

## Physics and planner

SI units, two-body DOP853 propagation, one controlled object+7 neighbours,3h horizon. Refine local closest approaches from r_rel dot v_rel roots;30s sampling,15s verification. Circular Gaussian encounter-plane Pc with independent numerical integration; explicit invalid/unsupported status.

37 candidates: no burn plus burn at300/900/1500s with tangential dv +/- .01,.05,.1,.25,.5,1m/s. Screen every changed-object encounter, at uncertainty sigma multipliers.5/1/2. Accept if every supported evaluated encounter Pc<1e-4; minimise dv then worstPc then earliest burn. No feasible candidate => abstain. Report dv as fuel proxy only.

Default RTN position standard deviations20/100/20m for controlled object and30/150/30m for others; radius5m/object. Prescribed synthetic uncertainty, not reconstructed or propagated real covariance. Exclude unsupported slow-relative-motion examples.

Required NASA Omitron/Alfano01/02 circular fixtures within.1% relative error, analytic isotropic check, rotation/object-swap invariance, invalid-covariance handling, propagation invariants. Fixed50 scenarios:10 benign,10 primary-only,20 secondary-hazard,10 infeasible; documented artificial composition and seeds. Preserve failures/abstentions in aggregate.

## Architecture and delivery

Flask/Gunicorn + NumPy/SciPy/pandas/sklearn/joblib; React/TypeScript/Vite/Recharts/SVG. API contract in CONTRACTS.md. Bounded process-pool screening, immutable JSON/CSV run artifacts. Build frontend locally, run API and all science on LinuxONE through existing SSH key. No need to install coding agent on s390x; agent uses local SSH tools. Never transfer key/token to remote project/public repo.

CLI commands: fetch-data, prepare-data, train, evaluate, validate-physics, benchmark-planner, benchmark-runtime, environment, serve. Record hashes, versions, seeds, runtime machine and raw predictions/scenario decisions. Distinguish local validation from actual LinuxONE execution.

## Order and scope control

Root coordinates three agents (ML,physics,frontend). First establish contracts/environment/data, then independent vertical slices, integrate continuously. By hour6 freeze features and model configuration; run held-out evaluation and independent review; reserve last2h for results/demo/submission. Remove 3D/extras if incomplete. No live spacecraft command, global catalogue optimisation, RL/GNN or LLM numerical decisions.

Submission: title contains team name, source link, <=3-minute video including LinuxONE instance/model, source attribution, architecture, reproducible evidence and limitations. Guidebook also requires two event AI labs; locate and complete actual organiser materials without claiming unknown equivalence.
