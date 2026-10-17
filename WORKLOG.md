# OrbitGuard — live handoff / resume file

Read this first when continuing with another AI. Keep it current after every meaningful milestone. Never put private-key contents, tokens, passwords, or final test-label values here.

## Objective and user instructions

### No-speech submission film (2026-10-17)

- Created `video/grand/` reproducible cinematic pipeline, preserving the old narrated pipeline. User-approved runtime is 170 seconds; final direction is minimalist, unboxed typography with detailed free NASA Aqua/TDRS spacecraft assets and NASA Blue Marble Earth imagery. Persistent animation disclaimers removed; short historical-replay and simulation labels remain.
- Actual LinuxONE instance/model identity, current evaluation artifacts and a fresh real screening run captured into ignored `video/out/grand-data.json`. Dashboard clips show prefix inference and experimental review transition, orbit/population graphs, pair-only vs whole-neighbourhood screening, precision–recall curves and scenario outcomes. The architecture shot distinguishes forecasting from separate synthetic planning.
- Generated `video/out/Datathon2_OrbitGuard.mp4` (original ambient soundtrack, no speech), `Datathon2_OrbitGuard_silent.mp4` (no audio stream), `VOICEOVER_SCRIPT.md`, `VOICEOVER_GUIDE.srt`, poster and contact sheet. Source credits are in `video/grand/CREDITS.md`; a minimal player/download page is `video/grand/watch.html` on the local asset server, port 8766.
- Both MP4 exports structurally verified at exactly 170 seconds, 1920×1080, 5100 frames (30 fps), with expected audio-stream presence and fast-start metadata. Both fully decode without errors. Rendering-plan/evidence tests and `git diff --check` pass. Generated verification report is `video/out/grand-verification.json`.
- The installed headless Chromium lacks H.264/AAC codecs; a separate 720p VP9/Opus WebM preview supports the local player without changing either 1080p MP4 master.
- Browser preview playback and seeking verified in Chromium: 170 seconds, 1280×720 preview, successful playback and seek to 146 seconds. The download masters remain verified 1080p. Local player: `http://127.0.0.1:8766/video/grand/watch.html`.
- Capture tuning: detailed assets use Draco decoding; Aqua draw calls consolidated while retaining geometry and vertex colours. Deterministic narrative capture uses 8–12fps source samples with a 30fps blended export; real dashboard clips retain actual timing. Each chapter uses a fresh browser. All source/assets remain local; no private-key contents enter generated video files. No Git commit or push.

### Event-to-alert replay update (2026-10-17)

- Added POST `/api/replay/update`: server-selected historical prefixes, default/experimental alert states, consecutive-prefix transitions, stable decision IDs and measured processing timestamps. No evaluation labels, automatic screening or spacecraft commands enter this flow.
- Main UI preserved. Replay adds a compact timeline, ordered response-paced playback, failure/retry handling and selected-prefix orbital illustrations. Production live ingestion remains explicitly out of scope; see `docs/EVENT_REPLAY.md`.
- Verification: 63 Python tests passed locally and natively on LinuxONE; build passed (existing large 3D chunk warning); strict UI audit had zero findings; fixture and real LinuxONE browser smoke passed. All 13 messages of encounter 1051 processed sequentially, with experimental review appearing at message 13 and repeated final update identity stable.
- Updated only isolated review copy `/home/linux1/orbitguard-review-szTtvXco`; separate preview on loopback 8002, local SSH tunnel 8083. Original systemd deployment on 8000 unchanged. No commit or push.

- Build a competitive working IBM Z Datathon 2026 project in about 10 hours.
- Product: historical satellite encounter risk forecasting plus synthetic avoidance planning that rejects secondary hazards.
- User has five teammates, Python/ML + web skills, working LinuxONE access. User says ask if in doubt and avoid assumptions.
- Concrete evidence is essential: ESA held-out evaluation, NASA numerical fixtures, simulator policy comparisons, actual LinuxONE execution.
- Current workspace: `/Users/bhavyapuri15/Desktop/Datathon2`.
- Confirmed team name: **Datathon2**. No existing GitHub repository. User/team will check prerequisite lab links with organiser; completion remains pending.
- Original guidebook: `/Users/bhavyapuri15/Downloads/Participant Guidebook_IBM Z Datathon 2026.pdf`.
- Dates/timezone: 17 October 2026, Asia/Singapore. No exact final submission timestamp supplied; original remaining window was 10 hours.

## Resume immediately

1. Read `CONTRACTS.md`, `IMPLEMENTATION_PLAN.md`, and agent logs under `docs/` if present.
2. Inspect files and `git status` (repository initialization may still be pending).
3. Run `.venv/bin/python -m pytest -q` once available; build frontend with `npm run build` inside `frontend`.
4. Check `artifacts/ml`, `artifacts/physics`, and `artifacts/runtime` for actual completed results. Never infer success from file presence alone; inspect provenance/status.
5. Continue coordinator work: Flask API/job runner, CLI/runtime benchmark, LinuxONE deployment, integration and documentation.
6. Reconnect to LinuxONE using the local key through SSH (see below), inspect current running processes before starting duplicates.

## Live agent ownership

- `/root` coordinator: API, CLI, packaging, runtime benchmarks, integration tests, LinuxONE, docs/submission package.
- `/root/data_ml`: `orbitguard/ml/**`, ML tests, data acquisition, `artifacts/ml/**`.
- `/root/physics`: `orbitguard/physics/**`, physics tests, NASA fixtures, scenarios, `artifacts/physics/**`.
- `/root/frontend`: `frontend/**`, React interface and browser checks.
- Maximum four concurrent agents including root. Do not spawn more unless an agent has finished.
- Agents share the filesystem. Avoid editing another active agent's files; coordinate additive contracts.

## Implemented / verified so far

- Created root `pyproject.toml`, `.gitignore`, `orbitguard/__init__.py`, command dispatcher `orbitguard/__main__.py`, and `CONTRACTS.md`.
- Created `.venv` using `/opt/homebrew/bin/python3.12`.
- Installed editable package with dev dependencies successfully. Local versions include Python 3.12, Flask 3.1.3, NumPy 2.5.4, SciPy 1.18.1, pandas 2.3.3, scikit-learn 1.9.1, joblib 1.6.0, pytest 9.1.1. Freeze actual versions before handoff; do not assume remote matches.
- Frontend agent reports npm install and TypeScript/production build passed. `frontend/dist` is available; browser/live API checks pending.
- ML agent started official ESA training archive and public-input downloads. Final model/results not yet verified by coordinator.
- Physics implementation and NASA fixture acquisition in progress. Coordinator validation pending.
- No API completion or end-to-end result should be claimed yet.

## LinuxONE access (non-secret metadata only)

- User supplied host `<VM_IP>`, user `linux1`.
- Private key is local workspace `key.pem`, permissions changed to 0600. It is ignored by Git. NEVER print/copy its contents or include it in rsync/source bundles.
- Command pattern: `ssh -i key.pem -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15 -o UserKnownHostsFile=/private/tmp/orbitguard-known-hosts linux1@<VM_IP> '<command>'`.
- First connection used `StrictHostKeyChecking=accept-new`, storing the host key in the temporary known-hosts file; later connections should retain host-key checks.
- SSH connection verified. Actual VM: s390x, Ubuntu24.04.5, Python3.12.3,3 CPUs,7.8GiB memory,45GB free disk. No Docker/Podman, no preinstalled scientific stack or shared notebook folder. Passwordless sudo available.
- Native Ubuntu s390x scientific packages are available: NumPy1.26.4, SciPy1.11.4, pandas2.1.4, sklearn1.4.1. Root dependency lower bounds adjusted to support these versions. Refit remote models; never unpickle local sklearn1.9 model on1.4.
- User cannot find prerequisite labs. Inspect existing notebooks/container and locate the official event materials. Do not claim labs completed without evidence.
- IBM event ML environment: https://github.com/linuxone-community-cloud/jupyter-lab-ml
- Supported image: `registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest`; record actual digest if used.

## Verified data sources and traps

- Official dataset: https://zenodo.org/records/4463683 (CC BY 4.0 in record metadata).
- ZIP size 221128642 bytes; MD5 `d19dc8875229f2f6893253c38adddc87`.
- Direct ESA train: https://kelvins.esa.int/media/public/competitions/collision-avoidance-challenge/train_data.zip
- Direct ESA public test: https://kelvins.esa.int/media/public/competitions/collision-avoidance-challenge/test_data.csv
- Zenodo content URL: https://zenodo.org/api/records/4463683/files/Collision%20Avoidance%20Challenge%20-%20Dataset.zip/content
- ZIP supports HTTP Range. Local header offsets / compressed lengths: test_data.csv 165 / 13659271; test_data_private.csv 13659544 / 1347012; train_data.zip 15006672 / 87718091 (stored). ZIP local headers determine data offsets; do not assume fixed header lengths.
- Released private test file has 2167 unique events, target column `true_risk`, many additional future feature columns. Only event_id/true_risk are allowed in evaluation. Never load those future fields into features.
- `risk` is already log10 probability. Features require time_to_tca >= 2 days. Eligible targets should be latest CDM with time_to_tca < 1 day.
- Use original event split, train-only CV, freeze model before final test evaluation. Raw archive includes test-related data and must not be used for training.
- Published clipped-latest baseline is about 0.694 challenge loss; independently reproduce before making model claims. Research attempt to reproduce timed out; that value is published, not locally verified yet.
- Clipping for published baseline: prediction >= -6 stays unchanged; otherwise -6.001. Challenge loss is high-risk log-space MSE / F2, reference high risk >= -6.

## Physics reference sources

- NASA source: https://github.com/nasa/CARA_Analysis_Tools
- Pin `ce0f00722c56808755ee0adbe47a4e3d56439484`.
- Circular expected Pc: Omitron `2.70601573490125e-05`, Alfano01 `1.46749549e-01`, Alfano02 `6.22226700e-03`.
- Relative tolerance 0.001, with consistent SI conversion of positions/velocities/covariance/radius.
- Simulator and historical data are independent evidence tracks; do not imply historical orbital reconstruction.

## Pending coordinator work

- Finish API routes, bounded background screening jobs, SPA serving, JSON error handling and result downloads.
- Add runtime environment/latency benchmark and meaningful integration tests.
- Inspect LinuxONE, use preinstalled scientific environment or supported image; actual remote training/evaluation still required.
- Run full checks, inspect agent outputs, review evidence logic, and perform browser QA.
- Prepare README, reproduction commands, architecture diagram, results/model card, demo script and submission checklist.
- Initialize Git and commit only source/docs/appropriate fixtures; key/data/artifacts excluded. No public repository publication or final video recording completed.

## Progress updates

- Recall follow-up, 2026-10-17: tested 60 training-only affine calibration variants and compared simple, classifier, residual and history-based escalation. Added `orbitguard/ml/guard.py` with baseline-preserving learned escalation, nested threshold validation, frozen policy/source/model fingerprints, and a lower-threshold comparator. Point forecasts and the planner remain unchanged; additional operator-review notices are explicitly experimental.
- Frozen retrospective guard result: 117/150 high-risk detections versus baseline 115/150, misses 33 versus 35, false alarms 64 versus 63, ESA loss 0.682760 versus 0.693961. Paired loss-difference CI [-0.03743,+0.00185] crosses zero. Nested development validation is weaker and has worse loss; this is not a replacement-default or blind-test superiority claim. Simpler threshold comparison also retained (118 detections,66 false alarms).
- Guard implementation verification: 50 tests pass locally and on native LinuxONE (7.47s remotely). All three additional review event IDs (1051,1362,1934) produce the experimental review flag while preserving the default forecast. Including review, p95 is 8.62ms over100 warmed service calls on those three cases. Fixture browser checks cover the new notice/evidence and default preservation. Frozen evidence and generated report: `docs/RECALL_IMPROVEMENT.md`, `docs/evidence/guard-review.json`, `docs/evidence/guard-verification.json`; reproduce with `train-guard`, `evaluate-guard`, `scripts/render_guard_review.py`. Original LinuxONE deployment remains untouched.

- Accuracy review, 2026-10-17 19:07 SGT: cloned repository into `/home/ubuntu/ibmdatathon/app`; read both supplied chat exports and participant guidebook. Preserve the existing console style, Encounters default and original tab order; extra context is optional under How it works.
- Correctness fixes: preserve raw low-risk forecasts instead of an artificial 1e-12 floor; split TCA searches at burn impulses; add Gaussian quadrature breakpoints; publish tightly verified risks/hazard flags and remove withheld trajectories; distinguish verification rejection; withhold stale forecast metrics; fail the evidence pipeline immediately on errors. UI fixes cover replay/stale responses, loading/empty/error states, and uncomputed/declined trajectory labels.
- Final source verified in isolated LinuxONE review directory `/home/linux1/orbitguard-review-szTtvXco`, using copies of the frozen model and the native scientific stack. Original `/home/linux1/orbitguard` deployment and systemd service were not updated. The review server uses loopback port 8001, with the test host's SSH tunnel on loopback 8081. Restart the deployed service after installing source or newly trained artifacts so its cached model matches the evaluated files.
- Final verification: 44/44 Python tests pass locally and on LinuxONE; all 3 NASA reference cases and 7 additional numerical checks pass; all 50 synthetic scenarios complete with 40 acceptable OrbitGuard plans, 0 introduced hazards and 10 correct abstentions. Production UI build, expanded fixture browser tests and full live LinuxONE browser smoke pass, including actual screening/downloads and mobile layout. Static UI audit has 0 findings. The existing large lazy-loaded 3D chunk still produces a non-fatal Vite size warning.
- Current measured evidence: learned raw log10 MAE improves from 15.152 to 5.160 after the floor fix, while ESA loss remains 1.828 versus baseline 0.694. Baseline detects 115/150 high-risk encounters, with 35 misses and 63 false alarms. Corrected residual ranking AP is 0.6984 versus baseline 0.6651, paired 95% difference CI [0.0020, 0.0612]. Forecast p95 is 8.40 ms; screening p95 is 1.76 s; 3-worker speedup is 2.78x.
- New training-only shrinkage and classifier experiments are retained separately and are not promoted: their retrospective improvement intervals cross zero. The public test was used in prior project versions; this is not a new blind test. Raw retrieved review artifacts/logs are in `artifacts/review-linuxone`; generated review, machine-readable evidence and judging guidance are in `docs/ACCURACY_REVIEW.md`, `docs/evidence/` and `docs/JUDGING_GUIDE.md`. Regenerate using `scripts/render_accuracy_review.py`. Changes are uncommitted and unpushed. Lab completion, final video and submission remain team actions.

- Initial implementation foundation complete; independent agent work running; frontend TypeScript/build and isolated Chrome desktop/mobile regression passed. Live integration pending.
- Flask API/job runner implemented in orbitguard/api.py; coordinator tests pending.
- API tests now pass:5 tests covering request/cutoff errors, job persistence/download, missing evidence, queue backpressure and explicit failures. `orbitguard/runtime.py` implements actual environment reporting and forecast/screening serial/parallel benchmarks; end-to-end execution pending.
- LinuxONE native scientific stack installed successfully; project venv at `/home/linux1/orbitguard/.venv` inherits apt packages. No container required for current project.
- Physics agent reports all3 selected NASA cases pass within1e-3 relative tolerance; coordinator full-suite review pending.
- Data is downloaded and verified by member CRC/SHA. Local strict training eligibility8293 events including66 high-risk; public test2167events. Do not reuse ordinary event_id across split as global key.
- Local held-out evaluation completed with frozen model: clipped latest baseline loss0.693961261, F2.739075, recall.766667,2167events/150highrisk. Learned numerical risk predictions worse(loss2.366948,F2.419118); default correctly remains baseline. Learned ranking AP.701367 vs rawlatest.665077; top10%recall.84vs.826667. No forecast-superiority claim permitted. Bootstrap ranking interval pending.
- Local simulator50scenario suite completed0failures: no_action10acceptable, pair_only20acceptable+20introducedsecondaryhazards+10correctabstentions, OrbitGuard40acceptable+0introducedhazards+10correctabstentions. Scenario composition is deliberately synthetic, never operational prevalence.
- Frontend live Chrome checks pass against actual API8000 and37-candidate simulation, primary/secondary views, download availability and mobile layout. UI now supports actual runtime metrics and separate learned/default forecasts.
- Remote source and data transfers completed. Remote package installation/data preparation/tests started in tool session63034; poll before starting overlapping jobs.
- ML downloaded real files; discovered source event IDs are separately numbered across official split. Agent investigating exact-row duplication and namespacing rather than invalid raw-ID overlap assertions.
- 2026-10-17 ~17:10 SGT: Full LinuxONE pipeline run via `scripts/run-linuxone-pipeline.sh` — all steps OK (train 112s, evaluate 7s, physics 0s, planner 133s, runtime 84s). s390x results: baseline loss 0.693961 reproduced; learned loss 1.828 (worse, baseline stays default); learned ranking AP 0.7005 vs 0.6651, bootstrap CI [0.0041,0.0644] excludes zero; NASA 3/3 pass; suite pair_only 20 introduced hazards vs OrbitGuard 0; forecast p95 8.45ms, screening p95 1.71s, 3-worker speedup 2.77x. Artifacts fetched to `artifacts/linuxone/`; `docs/RESULTS.md` generated by `scripts/render_results.py`.
- systemd `orbitguard` service installed, enabled and active on the VM (127.0.0.1:8000). Tunnel: `python3 scripts/linuxone.py tunnel --host <VM_IP> --key key.pem --known-hosts /private/tmp/orbitguard-known-hosts` → http://localhost:8080.
- Fixes: frontend close-up JSX build break (fragment), Decision brief now policy-aware (no contradictory "meets constraints" on pair-only tab), monitor y/x axis formatting, headline card shows selected (CV-chosen baseline) forecast, provenance panel shows dataset evidence, gzip for API JSON (+test; 26 tests). Smoke test now waits for real data in live mode.
- Docs added: README.md, docs/RESULTS.md, docs/DEMO_SCRIPT.md, docs/SUBMISSION_CHECKLIST.md. Remaining team actions are in the checklist (labs, GitHub repo, video, submission). Git has no commits yet.
- UI redesign: removed neon/glow theme, slogans, sidebar marketing card, redundant metric cards and decorative icons. New: top-bar navigation (Encounters / Manoeuvre planning / Validation), LinuxONE status indicator with tooltip, IBM Plex fonts, neutral light theme with dark mode via prefers-color-scheme, glossary tooltips (`Tip`/`Term` in App.tsx) on every technical term, plain-language page intros, recommendation headline with dynamic explanation, full-width clickable policy table, all-37-candidates table, geometry view with miss distance and explanation panel. Smoke test rewritten for new UI (fixture + live pass). Docs emoji-free; demo script updated to new labels.
- Visualisations added: `frontend/src/Globe.tsx` (three.js globe, Natural Earth land texture, Line2 orbits, CSS2D labels with occlusion dimming, zoom buttons), `Visuals.tsx` (lazy-loaded: OrbitalView with time slider/jumps/separation chart; EncounterOrbits from CDM elements, orientation illustrative), `Charts.tsx` (population scatter, PR curves, policy outcome bars), `ui.tsx` (shared Tip/Term/glossary/tokens). API: GET /api/population; MLService.ranking_curves() adds both PR curves to evidence. Static JS/CSS now gzipped (3D chunk 660KB → 239KB). 28 tests; fixture + live smoke pass; deployed on LinuxONE.
- Demo video: `video/` pipeline (narration.mjs, tts.mjs, scenes/*.html + lib.js, overlay.js, record.mjs, build.mjs). Output video/out/OrbitGuard_demo.mp4 (174.97 s, 1080p30, -16 LUFS), music-only version, SRT, poster. App scenes recorded live from LinuxONE via tunnel. See video/README.md.
