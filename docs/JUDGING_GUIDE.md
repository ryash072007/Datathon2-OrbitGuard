# Showing judges that OrbitGuard works

Use the supplied **Participant Guidebook, IBM Z Datathon 2026**, especially the submission requirements and technical judging rubric. Each of impact/theme alignment, originality, LinuxONE/AI use and execution is worth 10 points. Accuracy evidence supports the technical story; it does not replace the community impact or a clear working demonstration.

## Three claims with three kinds of evidence

| Claim | Show | Explain the boundary |
|---|---|---|
| We evaluate risk forecasts honestly | Validation: reproduced ESA baseline, recall, precision, missed alerts, confidence intervals, raw errors; download evidence JSON | Forecasts later reported risk, not observed collisions. The public test set is reused retrospectively. |
| The probability implementation has independent checks | NASA reference table and numerical regressions | These validate selected mathematical calculations, not the whole operational system. |
| Screening every nearby object changes the decision | Run the first synthetic scenario; compare pair-only vs OrbitGuard, the distance to C, rejected candidates and tight verification | Frozen synthetic stress tests; finite choices, simplified dynamics, prescribed uncertainty. |

The new results and fingerprints are in [ACCURACY_REVIEW.md](ACCURACY_REVIEW.md). The original measured deployment is documented in [RESULTS.md](RESULTS.md); do not conflate that historical report with a new run.

Do not call the prototype “99% accurate.” Most events are low risk, so a model that never detects a dangerous encounter can still have a high overall accuracy. Lead with how many high-risk encounters were found and missed. Show false alarms beside recall. Use confidence intervals to explain the uncertainty of improvements.

The forecast-floor fix repairs lost numerical information. The experimental shrinkage method and separate classifier remain experimental: their paired intervals cross zero. Present rejected experiments as evidence of a disciplined selection process, not new production gains. The latest-risk baseline stays the default because the original learned model has worse ESA loss.

## A video under three minutes

| Time | Action | Point to make |
|---|---|---|
| 0:00–0:20 | State the problem and show a sourced supporting fact | Satellite services matter to people; avoiding one encounter must not create another. Use a current attributed source for any satellite/debris count. |
| 0:20–0:45 | Show the actual LinuxONE instance, `uname -m`, running service and model fingerprint | Training, inference and screening run on IBM LinuxONE. Browser graphics alone do not prove that. |
| 0:45–1:15 | Replay one historical encounter and show the reference separately | Only messages at least 48 hours before closest approach enter the forecast. |
| 1:15–2:05 | Screen the first synthetic scenario; switch pair-only to OrbitGuard | Explain the risk/fuel tradeoff and secondary hazard in C using computed values on screen. |
| 2:05–2:40 | Show Validation, missed alerts, NASA checks and frozen-suite outcomes | Explain measured strengths and the remaining limits. Show actual platform timings, not estimates. |
| 2:40–2:55 | Show the architecture and finish | Human decision support; the tool does not command spacecraft. |

Rehearse against the actual app. Keep the final five seconds as buffer. If a live connection fails, use a clearly labelled recording captured from LinuxONE; never substitute fixture screenshots as evidence.

## Required submission checks

- Title contains the team name, for example **Datathon2_IBM Z Datathon 2026_OrbitGuard**.
- Include the GitHub repository, a compulsory video of at most three minutes, and links to the open-source resources used.
- The guidebook requires completion of both provided prerequisite labs: **Predictive AI Hybrid AI scenarios (multi-model)** and **Predictive AI + Generative AI**. Confirm the exact event notebooks and retain executed notebook evidence. The chat exports alone do not prove completion.
- Capture screenshots of the LinuxONE instance/model, architecture, service, test output and measured results. Security, containerization and compute claims need evidence of what was actually used.
- Do not describe CPU execution as accelerator/NNPA execution without measured runtime evidence. Prior chat discussion of an image pull or zDNN setup is not proof of acceleration.
- Retain dataset attribution and the explicit simulation assumptions. The project must meet the event's originality and hacking-window requirements.

## Before recording a revised deployment

Build the UI, run the evidence pipeline on LinuxONE, and confirm it finishes successfully. Restart the deployed service after installing source or newly trained artifacts so its cached model matches the evaluated files. The pipeline now stops on failure instead of continuing with stale outputs. The API also rejects forecast evidence whose model fingerprint no longer matches.

Download fresh evidence JSON from Validation. Check the model's before/after hashes match, the runtime architecture is `s390x`, and no required artifact is pending or stale. Keep the generated review report, logs and raw artifacts with the submission materials.

Use a native compatible environment for serialized models. The development machine's newer scikit-learn cannot necessarily load the LinuxONE model. Retrain in the target environment or use matching dependency versions; do not silently load an incompatible estimator.
