# Video script (target 2:40, hard limit 2:50)

Numbers not found in the repo docs are marked [VERIFY]. Placeholders in [BRACKETS] are measured at the end on the VM.

## Time-coded table

| Time | On screen | Voice-over |
| --- | --- | --- |
| 0:00-0:15 | Animated orbit view / 3D debris globe, warning emails stacking up. | Low Earth orbit is crowded. Tens of thousands of tracked objects [VERIFY] share it with working satellites, and operators get collision warnings constantly. Most are noise. A few are not. Each false alarm costs fuel, sleep and satellite lifetime, and each missed one could create thousands of fragments. Which warnings really matter? |
| 0:15-0:35 | Slide: "13,154 events", "12 of 97". | We used the European Space Agency's collision dataset: 13,154 real warning histories. In ESA's own challenge, only twelve of ninety-seven teams beat the naive baseline of simply trusting the latest warning. So a slightly better probability alone is not the answer. Operators need a next step they can trust. |
| 0:35-0:55 | Dashboard: event picker, then decision panel (ACT / WAIT / MONITOR with reasons). | We built decision support in four steps. First, decision. For each event we recommend Act, Wait or Monitor, with a calibrated probability, an uncertainty interval and plain reasons. A human always decides. |
| 0:55-1:15 | Burn options table; highlight best burn and the one with a new close approach. | Second, the dodge. We test 145 candidate burns in parallel. The best, half a metre per second, lifts the miss distance from five to twenty-two kilometres, and starts no new close call. A burn that dodges one object but pushes you toward another is ranked lower, because we screen every candidate against the whole catalogue. |
| 1:15-1:35 | Consequence panel + constellation bar chart; rank slope chart; 3D debris globe. | Third, consequence. If the pair did collide, how much debris, and which satellites would it threaten over thirty days? We model the breakup with NASA's standard model and spread the cloud forward in time. Probability and harm rank events differently: eleven of twenty change place by three or more. |
| 1:35-1:50 | Replay panel: decision changing as warnings arrive. Super-spreader network. | Watch the decision change as new warnings arrive. And a network sweep finds the objects most likely to start a chain reaction. |
| 1:50-2:05 | Brief panel with "grounded" badge. | Fourth, the brief. IBM Granite writes a short operator brief, and a guard rejects any number the tools did not produce. If the model fails, a template takes over, so the demo never breaks. |
| 2:05-2:30 | Terminal: `lscpu` showing s390x. Dashboard footer "s390x / big". `docker ps`. Speed-up chart. Granite log on-box. | All of this runs on an IBM LinuxONE instance. Here is lscpu: s390x, big-endian. Screening scales across [N] cores for a [VM SPEED-UP] speed-up. We converted Granite to big-endian format and it runs here, inside this container. Data never leaves the box, and every decision is written to a tamper-evident audit log. |
| 2:30-2:40 | Architecture SVG, then closing line on black. | Operators stay in control. Probability tells you how likely. We tell you what it would cost, and which dodge doesn't start a cascade. |

## Word count

Voice-over words: counted below (target about 400, limit 2:50 at roughly 150 wpm).

**Total spoken words: 368** (about 147 s at 150 wpm, plus pauses for screen cuts).

## Shot list and recording tips

- Record the screen at 1080p, 30 fps, browser zoom 110-125% so text is legible. Hide bookmarks and notifications.
- Pre-cache every job with `scripts/demo.py` so nothing waits on camera. Rehearse once with the cache warm, then record.
- Record VM shots (`lscpu`, `docker ps`, htop during the run, Granite log) separately; save stills to `docs/evidence/`.
- Panels by time: 0:35 decision; 0:55 burn options; 1:15 consequence and slope chart (3D debris globe, being built); 1:35 replay panel (being built) and network; 1:50 brief; 2:05 footer and terminal.
- Record voice-over separately, in a quiet room, and cut the video to it. Leave 1 s of silence at the start and end.
- Replace every [VERIFY] and [BRACKET] before export. Check the final length is under 3:00.

## Pitch Q&A prep

1. **Why not ML for risk?** We tried the benchmark honestly: the gain over naive is small (L 0.694 to 0.680) and only 66 high-risk events exist. Rules chosen by cross-validation are more explainable. We say so rather than overclaim.
2. **How accurate are TLEs?** About 1 km position error and no covariance. This is decision support for ranking and screening, not operational targeting.
3. **Is the consequence model validated?** Sanity-checked, not validated. Order of magnitude matches Iridium-Cosmos, and a hand density calculation matches the tool. Masses are assumed, no drag. Use it for relative ranking.
4. **Why LinuxONE?** Screening hundreds of burns and a catalogue-wide sweep are parallel and data-sensitive. On-prem big-endian Z keeps data in the box, and cores give [VM SPEED-UP]. Our 12-core PC reached 4.84x.
5. **What is the grounding guard?** It extracts every number from the brief and checks it against the tool facts. Any invented number, or a model failure, switches to a deterministic template. It checks numbers, not wording.
6. **What about real operators?** We have not tested with one. The tool recommends and explains; the human decides, and an audit log records it. Next step: validate with operator feedback and real covariance data.
