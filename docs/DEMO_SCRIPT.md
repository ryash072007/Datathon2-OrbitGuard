# OrbitGuard — 3-minute video script

Record the browser at `http://localhost:8080` through the SSH tunnel, so every screen is served live by LinuxONE. Before recording:

- Run `python3 scripts/linuxone.py tunnel --host <VM_IP> --key key.pem`.
- Hard-refresh once.
- Press "Screen manoeuvres" once so the first job has warmed up.

Target length: 2:50. Every number spoken below appears on screen and comes from `docs/RESULTS.md`.

| Time | Screen / action | Narration |
|---|---|---|
| 0:00–0:20 | Title card, then a terminal showing `ssh … 'uname -m; systemctl is-active orbitguard'` printing `s390x` / `active` | "More than ten thousand active satellites share low Earth orbit. When an operator dodges one object, the new orbit can head straight into another, and one collision makes debris that threatens everything nearby. OrbitGuard checks the whole neighbourhood before recommending a burn. Everything you'll see runs live on IBM LinuxONE." |
| 0:20–0:55 | **Encounters** tab. Encounter #891 is selected; press the play button to replay its messages. Scroll to the globe of the two orbits and the population chart ("each dot is one of 2,167 encounters; the vertical bands are orbits crowded with debris"). Hover the question-mark icon next to "Latest reported value" to show the explanations. Point at latest reported value, learned model, and the final reported value. | "These are real ESA conjunction alerts. We only use information available at least 48 hours before closest approach. Each forecast comes back from LinuxONE in about 8 milliseconds. We were strict about evaluation: we froze the model before touching ESA's released test labels, and we reproduced ESA's published baseline score of 0.694 exactly." |
| 0:55–1:55 | **Manoeuvre planning** tab. Scenario "Avoid B without endangering C". Press **Screen manoeuvres** and read the recommendation headline. In **Compare policies**, click the **Avoid B only** row. Scroll up to the **Orbital view**, press **Closest approach with C (T+100:00)**: the globe flies to the encounter and the distance chart's green line dips to 15 m. Then click the **OrbitGuard** row: the dip disappears. Optionally show the close-up geometry view. | "Satellite A is on course to meet B, with a collision probability of 1.5 in a hundred. LinuxONE screens 37 candidate burns against every object, at three uncertainty levels, in under two seconds. The cheapest fix that looks only at B burns minus 5 centimetres per second. It clears B, but it puts A on a path to C at 2 in a hundred, which is worse than doing nothing. OrbitGuard rejects that burn and picks plus 5 centimetres per second instead. That's the same fuel, every encounter is below one in ten thousand, and the recommendation explains exactly why." |
| 1:55–2:40 | **Validation** tab. Scroll through: forecasting table and ranking comparison, then NASA reference cases (all Pass), then the 50-scenario policy table, then speed on this server. | "Is it right? Our collision-probability code matches NASA's published reference cases to within three parts per million. Across 50 frozen stress-test scenarios, pair-only avoidance introduced 20 secondary hazards and OrbitGuard introduced zero, using the same average fuel. It also correctly said 'no safe option' in all 10 impossible cases. On real ESA data, our learned model ranks dangerous encounters better than the baseline, and that improvement holds up statistically. Where it didn't beat the baseline, on the raw risk value, we say so and keep the baseline. Parallel screening on LinuxONE's three cores runs 2.8 times faster." |
| 2:40–2:55 | Architecture diagram from the README | "Real data, independent checks, measured on IBM Z. OrbitGuard gives operators one decision that protects every nearby orbit." |

## Backup if the network fails

Play a pre-recorded screen capture of the same flow. Also keep `docs/RESULTS.md` and `frontend/test-results/live-*.png` open as stills.

## Phrases to avoid

- "Predicts collisions." Say instead: forecasts the later reported risk estimate.
- "Guaranteed safe." Say instead: no hazardous encounter found within the simulated horizon and the evaluated candidate set.
- "Our model beats ESA." The model beats the baseline on triage ranking, not on challenge loss.
