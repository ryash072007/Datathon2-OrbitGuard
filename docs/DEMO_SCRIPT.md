# OrbitGuard: video script

**Length:** target 2:55, hard limit 3:00 (guidebook). **Narration:** about 400 words, so a calm pace with room to breathe.
**Guidebook checklist:** the problem ✔ the data behind it ✔ the solution, demonstrated ✔ how it uses IBM Z: the tech stack,
the LinuxONE instance and the model ✔. Title on the first and last card: `[Datathon2_IBM Z Datathon 2026 Project]`.

**How it should feel.** One continuous flight through a live system. The camera never sits still on a static page: every
shot is either something moving (a globe turning, a stream ticking, a bar filling) or a slow, deliberate scroll. Cuts
are 10-frame cross-dissolves. Each number the narrator says appears on screen at the same moment, as a caption chip or
as the console's own reading. Music is a soft ambient bed ducked under the voice (the CC0 track in
`video/assembly/music/`).

Numbers in **{braces}** are read from the VM on recording day (sources at the bottom). Everything else on screen is
served live by the LinuxONE VM through the SSH tunnel.

---

## The script

### 1. Cold open: the sky is crowded (0:00 to 0:16)

**On screen:** Black. The 3D globe fades up, slowly turning. Thousands of points drift in: satellites in blue, debris in
orange. A caption chip appears with each number.

> Right now, about forty thousand objects are tracked in orbit around Earth. Only eleven thousand of them are working
> satellites. The rest is debris, and all of it is moving at nearly eight kilometres a second.

**Caption chips:** `~40,000 tracked objects` · `~11,000 active satellites` (ESA Space Environment Report 2025).

### 2. The problem: dodging is routine, and dodging is risky (0:16 to 0:38)

**On screen:** The globe zooms toward low Earth orbit. Two stat cards slide in from the right, one after the other.
Then a simple animated sketch: satellite A swerves around B and the dotted path runs straight into C, with C pulsing red.

> Dodging has become routine. One operator made almost a hundred and fifty thousand avoidance manoeuvres in just six
> months. Every one is a decision made under uncertainty. Get it wrong and you get 2009, when two satellites collided
> and the debris is still up there. And there's a trap: a dodge that clears one object can steer you into another.

**Stat cards:** `148,696 collision-avoidance manoeuvres in 6 months` (Starlink, SpaceX filing to the FCC, Dec 2025) ·
`2009: Iridium 33 × Cosmos 2251, the first satellite-on-satellite collision`.

### 3. The data: warnings are noisy (0:38 to 0:52)

**On screen:** **Encounters** tab. The population chart animates in, one dot per encounter. A highlight sweeps across the
few red dots.

> The warnings are noisy, too. In ESA's real alert data, only sixty-six of eight thousand events end up high risk. In
> ESA's own competition, only twelve of ninety-seven teams beat the simplest rule there is: trust the latest message.

**Caption chips:** `66 of 8,293 events end high-risk` · `12 / 97 teams beat the baseline` (ESA Collision Avoidance Challenge).

### 4. Meet OrbitGuard, on IBM LinuxONE (0:52 to 1:04)

**On screen:** A terminal types itself (pre-recorded capture, sped up 1.5×):
`ssh linux1@…` → `uname -m` prints **s390x** → `lscpu | grep -E 'Byte Order|Machine type'` prints **Big Endian / 9175** →
`grep -o -m1 nnpa /proc/cpuinfo` prints **nnpa** → `docker ps` shows the **orbitguard** container →
`tail -4 artifacts/pipeline/status.log` shows `OK … DONE`. Dissolve to the console header: the green
**"s390x · IBM LinuxONE"** badge and the real-time strip.

> OrbitGuard is decision support for that operator, and it runs here, on an IBM LinuxONE z17. A big-endian machine
> with an AI accelerator, Telum, built into the processor.

### 5. Detect, in real time (1:04 to 1:22)

**On screen:** **Encounters**, an encounter selected, press **Play stream**. Messages tick in one by one. Each gets a latency
badge, and the Act / Wait / Monitor card updates. Push in on the ticker line *"next message arrived 8.1 h later; decision
took … ms"*. The header strip reads the live p50 and p95.

> Here's a real encounter from ESA's data, replayed message by message. Every alert gets a decision, act, wait or
> monitor, with a probability, an interval and its reasons, in about {forecast_p50_ms} milliseconds. The next message
> arrives hours later. The operator never waits on us.

### 6. Decide: the dodge that creates a new collision (1:22 to 1:46)

**On screen:** **Manoeuvre planning**, scenario *"Avoid B without endangering C"*, press **Screen manoeuvres**. In **Compare
policies** click **Avoid B only**. The orbital view flies to *Closest approach with C*, and the distance line dips almost
to zero. Click **OrbitGuard**: the dip disappears. Caption: `Pc maths matches NASA CARA reference cases`.

> Satellite A is heading for B. The cheapest dodge that only looks at B clears it, and steers A into C. OrbitGuard checks
> every burn against every object, at three levels of uncertainty, and picks a different burn for the same fuel. Across
> fifty stress tests, pair-only checking created twenty new hazards. OrbitGuard created none.

**Caption chip:** `50 scenarios · pair-only: 20 new hazards · OrbitGuard: 0` (VM, `artifacts/physics/benchmark.json`).

### 7. The real sky: ISS, tomorrow (1:46 to 2:12)

**On screen:** **Live catalogue**, NORAD 25544, press **Find and screen** (pre-warmed, so it lands in a few seconds). The
stage-timing bar fills left to right. Pan down the candidate-burn table; the recommended row is highlighted. Glide past
*If they collide*. Stop on **Operator brief**: the *Granite* tag and *Grounded* badge. Click the Ask chip *"What if I burn
one orbit later?"*. The answer appears with its tool chips.

> Now the real sky. The ISS has a close approach tomorrow, under four kilometres. LinuxONE screens {n_burns} burns
> against {n_objects} objects and recommends a burn of twenty centimetres a second. IBM Granite, running on this
> machine, writes the brief, and answers the operator's questions. Every number it says is checked against the maths.

**Caption chips:** `{n_burns} burns × {n_objects} objects · {screen_total_s} s on 3 cores` · `Granite 3.3 · on-box · big-endian`.

### 8. Honest AI: where it helps, and where it doesn't (2:12 to 2:36)

**On screen:** **Validation**, section *"Where the AI helps, and where it doesn't"*. Slow scroll: the forecasting card (grey
*not significant*), then stop on the **Learned burn search** card (green *cheaper*, 30 / 10 / 0). Quick flash of
`docs/DATA_BOUNDARIES.md`'s diagram.

> We tested every AI part against a simple alternative, and we show the losses. Forecasting the final risk? Not
> significantly better, so we keep the baseline. But a learned search, a Gaussian process proposing burns that the
> physics then verifies, finds safe burns using twelve and a half percent less fuel, and never does worse.

**Caption chips:** `Forecast gain: not significant` · `Learned search: −12.5% Δv, 30 wins / 0 losses` (VM, 50 scenarios).

### 9. Why IBM Z (2:36 to 2:52)

**On screen:** A split screen. Left, a terminal printing the NNPA benchmark table (CPU vs Telum rows per second). Right, the
architecture diagram from the README, with each box lighting up as it's named.

> On Telum, the risk model scores {nnpa_speedup_1m} times faster through IBM's zDNN plugin. Granite runs locally, so no
> data leaves the machine. And every forecast, burn and operator choice goes into a tamper-evident audit chain.

**Caption chips:** `Telum NNPA · TensorFlow + IBM zDNN` · `IBM Granite on s390x` · `hardened systemd + container` ·
`SHA-256 hash chain`.

### 10. Close (2:52 to 3:00)

**On screen:** The globe pulls back to the whole Earth. The title card fades in: **OrbitGuard**, *Team Datathon2*,
`[Datathon2_IBM Z Datathon 2026 Project]`, *IBM Z Datathon 2026*.

> Avoiding one satellite shouldn't put another in danger. OrbitGuard makes sure it doesn't.

---

## Numbers to read on recording day

| Placeholder | Value now (VM, 2026-10-17) | Source |
| --- | --- | --- |
| `{forecast_p50_ms}` | 45 | `artifacts/runtime/metrics.json` (forecast p50; p95 49 ms), or the header strip |
| `{n_burns}`, `{n_objects}`, `{screen_total_s}` | 144, 6,753, 77 | Live catalogue stage bar for 25544 (`artifacts/live/out/facts_25544.json`, `stage_timings`) |
| `{nnpa_speedup_1m}` | 3.4 | `artifacts/nnpa/nnpa_bench_yash-ibm.json` (1M rows: 888k vs 259k rows/s) |

Fixed facts and where they come from:
- 40,000 tracked, 11,000 active: [ESA Space Environment Report 2025](https://www.esa.int/Space_Safety/Space_Debris/ESA_Space_Environment_Report_2025).
- 148,696 Starlink manoeuvres in the six months to 30 Nov 2025: SpaceX's semi-annual report to the FCC (31 Dec 2025).
- 66 of 8,293 and 12 of 97: the ESA Collision Avoidance Challenge data and Uriot et al. (README credits).
- 20 vs 0 hazards, 12.5% less Δv, the burn recommendation: VM artefacts listed in the README Results.

If the ISS event has passed by recording time, or a new TLE changes the closest object, re-run **Find and screen**
and read the new values off the screen. Change the line "under four kilometres" to match.

## Before recording (10 minutes)

1. Check the service: `ssh linux1@148.100.76.224 'docker ps --filter name=orbitguard; curl -s localhost:8080/api/platform'`.
2. Open the tunnel and the console at `http://localhost:8080`, then hard-refresh.
3. Warm up: play one encounter stream (fills the latency strip), screen the B/C scenario once, run **Find and screen** for
   25544, and wait for the Granite brief to finish (several minutes on 3 vCPUs; it's cached after that). Ask one question.
4. Browser at 1440×900, 100% zoom, cursor highlight on, notifications off.
5. Record each section as its own clip (the scripted recorder in `video/assembly/record.py` gives smooth 60 fps scrolls),
   then assemble with `video/assembly/assemble.py`: captions, chips, music bed, loudness.
6. Check the final length is under 3:00 before uploading.

## Backup

If the tunnel or the VM fails mid-recording, use the pre-recorded clips of the same flow and the terminal captures in
`docs/vm_capture/`. Never re-record numbers on the laptop: the laptop isn't LinuxONE.

## Phrases to avoid

- "Predicts collisions." Say: forecasts the later reported risk.
- "Guaranteed safe." Say: no hazardous encounter found among the screened burns and objects.
- "Our model beats ESA." It doesn't. Say we tested it and kept the baseline.
- "AI decides the burn." Physics decides what's safe; the learned search only proposes; the operator decides.
- "Granite verifies." The guards reject text that disagrees with the facts. They don't prove it true.
- "Real-time collision prediction." Say: a decision for every new message in milliseconds; a full screen in about a minute.
- Avoid "leverage", "seamless", "cutting-edge", "revolutionary".
