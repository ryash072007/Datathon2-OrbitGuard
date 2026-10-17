# OrbitGuard implementation contracts

Approved architecture: React/TypeScript/Vite frontend, Flask Python API, scikit-learn historical forecasting, SciPy orbital simulation, LinuxONE execution. Historical data and synthetic scenarios must be visibly distinguished. Never hard-code performance claims or silently use mock results.

## Ownership

- Coordinator: `orbitguard/api.py`, `orbitguard/__main__.py`, root packaging, integration tests, deployment, docs.
- ML agent: `orbitguard/ml/**`, `tests/test_ml*`, `artifacts/ml/**`, dataset acquisition and ML dependencies communicated to coordinator.
- Physics agent: `orbitguard/physics/**`, `tests/test_physics*`, `artifacts/physics/**`, scenario fixtures.
- Frontend agent: `frontend/**` only. Do not edit root Python files.

## Python service interfaces

All values returned by services must be JSON serializable and finite (use null rather than NaN/Infinity). Service roots are pathlib.Path objects pointing to the repository/run root. Constructors must remain cheap and not train/download anything. Services may lazily load frozen artifacts. Missing artifacts must be explicit, never invented.

`orbitguard.ml.service.MLService(root)`:
- `list_events(limit=100) -> list[dict]`
- `get_event(event_id: str) -> dict` (historical replay; label future/reference values explicitly)
- `forecast(history: list[dict]) -> dict`
- `evidence() -> dict`

`orbitguard.physics.service.PhysicsService(root)`:
- `list_scenarios() -> list[dict]`
- `get_scenario(scenario_id: str) -> dict`
- `screen(scenario_id: str, overrides: dict | None = None) -> dict`
- `evidence() -> dict`

Use ValueError for invalid user inputs and KeyError for unknown IDs. Return structured readiness in evidence if results are absent. CLI modules each expose `main(argv: list[str]) -> int`.

## HTTP endpoints

- GET `/api/health`: `{status, architecture, platform, model, build_version}`
- GET `/api/events?limit=100`: `{events: [...]}`
- GET `/api/events/<event_id>`: historical event detail
- POST `/api/forecast`: `{history: [CDM rows...]}` -> ML forecast
- GET `/api/scenarios`: `{scenarios: [...]}`
- GET `/api/scenarios/<scenario_id>`: synthetic scenario detail
- POST `/api/screen`: `{scenario_id: str, overrides?: {}}` -> 202 `{job_id, status}`
- GET `/api/jobs/<job_id>`: `{job_id, status: queued|running|completed|failed, result?, error?, elapsed_seconds}`
- GET `/api/evidence`: `{ml: {}, physics: {}, runtime: {}}`
- GET `/api/runs/<job_id>`: completed run JSON download
- Errors: `{error: {code, message}}` and suitable HTTP status.

## Recommended frontend-facing data fields

ML event summaries: `event_id`, `latest_log10_pc`, `time_to_tca_days`, `message_count`, optional `forecast_log10_pc`.
ML forecast: `event_id`, `baseline_log10_pc`, `forecast_log10_pc`, `model_name`, `model_version`, `cutoff_days: 2`, `elapsed_ms`, `warnings: []`. Forecast is a later ESA risk estimate, not a calibrated prediction that a collision will occur.
Scenario summaries: `scenario_id`, `name`, `description`, `kind`, `source: synthetic`.
Scenario detail: include objects, positions/trajectories with explicit units, horizon, assumptions, and view/plot data sufficient for SVG visualization.
Screening result: `scenario_id`, `source: synthetic`, `status`, `candidates_evaluated`, `elapsed_ms`, `recommendation`, `policies` (no_action, pair_only, orbitguard), `candidates`, `assumptions`, `trajectories`. Each policy includes `accepted`, `delta_v_mps`, `burn_time_seconds`, `primary_pc`, `worst_secondary_pc`, `worst_pc`, `reason`. Recommendation can be null on abstention.

Agents may add fields, but must communicate schema changes early. Frontend must tolerate absent optional fields and clearly display missing evidence.

## Evaluation invariants

- Original ESA test labels are evaluation-only. Read only event_id/true_risk from the private file.
- Features use messages at least 2 days before TCA. Split by event.
- Reproduce published clipped-latest baseline (~0.694 loss) before making model comparisons.
- Physics has independent NASA expected-value tests. Simulation is two-body/impulsive and explicitly synthetic.
- All metrics come from artifacts. Actual platform is detected, never claimed as LinuxONE on local hardware.
