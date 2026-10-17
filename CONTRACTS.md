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
- `replay_update(event_id: str, message_count: int) -> dict`: process the historical prefix and compare its alert with the preceding prefix, without reading evaluation labels.
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
- POST `/api/replay/update`: `{event_id: str, message_count: int}` -> `{update_id, source: historical_replay, message_count, total_messages, forecast, alert: {state, previous_state, changed}, action, received_at, completed_at, processing_ms, scope}`
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

Replay is stateless and request-driven, not a live ingestion service or durable message broker. The server selects chronologically ordered prefixes from historical inputs; client-supplied histories and final labels are not accepted by the replay endpoint. The stable update ID fingerprints the selected inputs and forecast (excluding timing), so repeated requests do not create additional alerts or screening jobs. Timings are newly measured on every request. Alert transitions always compare adjacent historical prefixes, not the last request received; out-of-order requests cannot mutate another replay. A processing failure publishes no successful update. The UI ignores superseded responses, pauses on failure, offers retry, and waits for completion before advancing playback.

`high_risk` means the default forecast is at least 10^-6; `additional_review` is the separate experimental learned escalation; `monitor` is not a safety clearance. Processing latency includes loading/selecting the prefix and forecasting both current and preceding states. Browser round-trip timing also includes transport and response handling, not upstream observation latency. These are distinct from existing single-forecast benchmark timings. No replay alert automatically maps anonymised ESA encounters to synthetic geometry or commands a manoeuvre.

- Original ESA test labels are evaluation-only. Read only event_id/true_risk from the private file.
- Features use messages at least 2 days before TCA. Split by event.
- Reproduce published clipped-latest baseline (~0.694 loss) before making model comparisons.
- Physics has independent NASA expected-value tests. Simulation is two-body/impulsive and explicitly synthetic.
- All metrics come from artifacts. Actual platform is detected, never claimed as LinuxONE on local hardware.
