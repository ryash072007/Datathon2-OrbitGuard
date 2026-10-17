# OrbitGuard: 3-minute video script (merged system)

Guidebook requirement: 3 minutes or less, covering the problem, the data behind it, the solution, and (most
important) how it uses IBM Z: the tech stack, the LinuxONE instance and the model. Target 2:50, hard maximum 3:00.

## Before recording

1. Deploy the merged build and run `bash scripts/run-linuxone-pipeline.sh` on the VM, with Snap ML installed and
   `GUARDIAN_MODEL_PATH` set so the optional `zai-*` and `guard-eval` stages run. Then run `bash scripts/evidence.sh`.
2. Open the tunnel (`python3 scripts/linuxone.py tunnel --host <VM_IP> --key key.pem`) and record the browser at
   `http://localhost:8080`, so every screen is served live by LinuxONE. Hard-refresh once.
3. In **Live catalogue**, press **Find and screen** for NORAD 25544 once beforehand so the brief, the Ask model and
   the screen are warm. Ask one question before recording so the first answer is not a cold start.
4. **Fill in every `{placeholder}` below** from the named artefact, and check each spoken number is visible on
   screen in that shot. If an artefact is missing, cut that sentence. Do not improvise a number.
5. Check the final cut is 3:00 or less before uploading.

Numbers marked "README" were already measured on LinuxONE (see README "Results") and are spoken as written.

## Timed script

| Time | Screen / action | Narration | Words |
|---|---|---|---|
| 0:00-0:15 | Title card, then two stat cards. Card 1: "66 of 8,293 ESA training events end at high risk". Card 2: "50 stress scenarios: pair-only avoidance created 20 new hazards, OrbitGuard 0" | "When you dodge one satellite, you can steer into another. In our fifty test scenarios, checking only the original object created twenty new hazards. And in ESA's data, only sixty-six of 8,293 events end up high risk. OrbitGuard checks everyone nearby before it recommends a burn." | 46 |
| 0:15-0:30 | Terminal on the VM. Run `uname -m`, `lscpu` (z17 machine type), `grep -c nnpa /proc/cpuinfo`, `systemctl is-active orbitguard`, `ls -lh artifacts/llm/*.gguf`. Show `s390x`, the z17 line, `nnpa`, `active`, and the two Granite files | "This is the LinuxONE instance. It's s390x, a z17, and that nnpa flag is the Telum AI accelerator. OrbitGuard runs here as a service, next to the Granite models." | 29 |
| 0:30-1:05 | **Live catalogue** tab. NORAD 25544 analysed. Point at Situation (ISS and its threat object, miss `{live.miss_km}` km, Pc), "Objects screened", then the Recommendation card and its pair-only comparison, then the learned-search line (`{optimise.live_dv_mps}` vs grid `{optimise.live_grid_dv_mps}` m/s). Source: `artifacts/live/` facts for 25544 and `artifacts/optimise/evidence.json` | "Here's a real conjunction with the ISS. We checked {live.n_burns} burns against {live.n_objects} objects in {live.screen_s} seconds. A pair-only check would pick a burn that makes a new close approach. The all-object rule throws it out. Then the learned search looks between the grid points and finds a cheaper burn, {optimise.live_dv_mps} metres per second against {optimise.live_grid_dv_mps}. Physics re-checks it before we recommend it." | 63 |
| 1:05-1:30 | Scroll to **Operator brief** (point at the Granite tag and the grounded badge), then **Ask OrbitGuard**. Click the chip "What if I burn one orbit later?". When the answer arrives, point at the tool chips, "Numbers grounded" and the "Guardian: passed" badge | "Granite wrote that brief, on this machine. Now I'll ask a question. What if I burn one orbit later? Granite picks read-only tools, and these chips show what it looked up. The answer has to pass two checks, a number guard and Granite Guardian. If either fails, you get a plain template instead." | 53 |
| 1:30-1:50 | **Encounters** tab. Select an encounter, press play. On the decision card point at the ACT, WAIT or MONITOR badge, P(high) and the line "Snap ML second opinion: P(high) {snapml.p_high} · {snapml.backend} · {snapml.latency_ms} ms" | "Back to the ESA alerts. Each one gets Act, Wait or Monitor. A Snap ML model gives a second opinion, scored on the Telum accelerator in {snapml.latency_ms} milliseconds. When the two disagree, it flags the event for review." | 38 |
| 1:50-2:20 | **Validation** tab, section "Where the AI helps, and where it doesn't". Scroll the cards: Forecasting (CI crosses zero), Workload, Burn search (ratio 0.875, 30 wins, 0 losses), Guard evaluation (`{guard_eval.guardian_caught}` of `{guard_eval.n_bad}`). Sources: `artifacts/ml/decision_evidence.json`, `artifacts/ml/workload_evidence.json`, `artifacts/optimise/evidence.json`, `artifacts/llm/guard_eval.json` | "We tested every AI part against a simple alternative, and we show the losses too. Forecasting the final risk? Not significant, so we keep the baseline. Ranking? A little better. The learned burn search uses twelve and a half percent less delta-v, and never loses. Guardian caught {guard_eval.guardian_caught} of {guard_eval.n_bad} bad briefs, including ones with no wrong number." | 58 |
| 2:20-2:45 | Split screen. Left: **Telum** card, or terminal `orbitguard zai-bench` table (CPU vs zDNN, `artifacts/zai/snapml_bench_*.json`). Then `nnpa-bench` (`artifacts/nnpa/nnpa_bench_*.json`). Then the Granite and Guardian `.gguf` listing. Then `cpacf_crypto.txt` (msa flags and hashlib MiB/s). Last, `systemctl status orbitguard` and the Dockerfile | "On the box, Snap ML trees run {zai_bench.speedup_1M} times faster on zDNN than CPU at a million rows. The Keras model on NNPA is 2.67 times faster. Granite and Guardian run from big-endian files, so nothing leaves the machine. Our audit hashes use the CPACF crypto instructions, {cpacf.sha256_mibps} MiB per second. It runs under hardened systemd, or in a container." | 60 |
| 2:45-2:52 | README architecture diagram | "A human still decides. OrbitGuard just makes sure the burn is safe for everyone nearby, and tells you where the AI doesn't help." | 23 |

**Narration total: 370 words** (46 + 29 + 63 + 53 + 38 + 58 + 60 + 23, counting each `{placeholder}` as one word; at about 150 words per minute that is roughly 2:30 of speech, leaving room for pauses and screen changes).
Recount after filling in the placeholders. If the cut runs over 3:00, drop the 1:30-1:50 row first.

## Artefact sources for each placeholder

| Placeholder | Where it comes from (VM, at recording time) |
|---|---|
| `{live.miss_km}`, `{live.n_burns}`, `{live.n_objects}`, `{live.screen_s}` | Situation and "Objects screened" cards, from `artifacts/live/` facts for NORAD 25544 (`orbitguard screen-live`) |
| `{optimise.live_dv_mps}`, `{optimise.live_grid_dv_mps}` | Learned-search line on the Recommendation card, `artifacts/optimise/evidence.json` (live block) |
| `{snapml.p_high}`, `{snapml.backend}`, `{snapml.latency_ms}` | Encounters decision card, live from `/api/...` forecast second opinion (needs `artifacts/zai/snapml_evidence.json`) |
| `{guard_eval.guardian_caught}`, `{guard_eval.n_bad}` | `artifacts/llm/guard_eval.json` (`orbitguard guard-eval --n 40 --seed 0`) |
| `{zai_bench.speedup_1M}` | `artifacts/zai/snapml_bench_*.json` (`orbitguard zai-bench`), CPU time over zDNN time at 1M rows |
| `{cpacf.sha256_mibps}` | `cpacf_crypto.txt`, the "hashlib.sha256 over 64 MiB" line, written by `scripts/evidence.sh` |

Spoken as written, no placeholder: 20 vs 0 hazards and 2.67x NNPA (README, measured on LinuxONE); 66 of 8,293
(ESA data); "twelve and a half percent less delta-v" (the optimise evidence, ratio 0.875; confirm it still matches
the VM run, and if it differs, turn it into a placeholder).

## Backup if the network fails

Play a pre-recorded capture of the same flow taken from the VM. Label it as a recording. Never substitute fixture
screenshots as evidence. Keep `docs/RESULTS.md`, `docs/vm_capture/` and `frontend/test-results/live-*.png` open as stills.

## Phrases to avoid

- "Predicts collisions." Say instead: forecasts the later reported risk estimate.
- "Guaranteed safe." Say instead: no hazardous encounter found within the simulated horizon and the evaluated candidate set.
- "Our model beats ESA." The model beats the baseline on triage ranking, not on challenge loss.
- "The AI decides" or "the AI recommends the burn." Physics decides what is safe; the AI proposes and explains; the operator chooses.
- "Granite verifies" or "Guardian proves." The guards reject bad text; they don't prove it true.
- "Runs on the accelerator" for anything whose backend line doesn't say zDNN or NNPA. Say CPU if it ran on CPU.
- "Encrypted by CPACF" as a blanket claim. Say: hashing goes through OpenSSL, which uses CPACF; Secure Execution is a design note.
- "Machine learning improves the forecast." It doesn't, significantly. Say: we kept the baseline.
- Buzzwords: "leverage", "seamless", "cutting-edge", "revolutionary", "in today's world", "game-changing", "AI-powered".
- Any number that is not on screen in that shot, or not from a VM artefact or the README's LinuxONE results.
