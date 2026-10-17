# Phase 5: Super-spreader network, LLM brief and dashboard

## In one sentence
We find the objects most likely to start a debris chain reaction, have a local AI model write a checked operator brief, and show everything in one web dashboard.

## Why it matters
Not all objects are equally dangerous. A dead rocket body that passes near hundreds of others can seed a cascade if it breaks up. Operators also need a short, trustworthy summary, not ten tables. This phase gives them both, and the AI text can never quote a number the tools did not produce.

## How it works
1. **Build the network.** Every catalogue object (about 17k: active satellites, LEO rocket bodies and the major debris clouds) is compared with every other over 24 hours. Two objects get a link (an "edge") if they pass within 10 km. Think of it as a social graph where "friends" are objects that nearly meet.
2. **Use small time steps.** A first version sampled positions every 60 s. LEO objects cross at 7-15 km/s, so they jump 400-900 km between samples. That version missed fast crossings and found only 8,132 edges, mostly Starlink neighbours. The fix is 10 s steps. A KD-tree (a fast "who is nearby?" index) searches a widened radius of 10 km plus max speed times half a step. Then the exact closest approach inside each step is computed from relative velocity.
3. **Score super-spreaders.** Score = number of distinct neighbours x log10(assumed mass) x shell density (how crowded that altitude band is).
4. **Collect facts.** The decision layer, screener, consequence engine and network write one facts file.
5. **Write the brief.** IBM Granite 3.3 2B Instruct runs locally through llama.cpp. It writes six sections: Situation, Risk, Options, Consequence if no action, Recommendation, Uncertainties.
6. **Grounding guard.** The guard pulls every number out of the brief and checks it against the facts. If any number is invented, or the model fails, a deterministic template brief is used instead. The demo never breaks.

The Flask dashboard has eight panels: event picker; risk and Act/Wait/Monitor decision with reasons; burn options table; consequence with a constellation bar chart; probability-vs-harm rank slope chart; super-spreaders table and network picture; the brief with backend and grounding badges; and a footer showing CPU architecture and byte order. Heavy jobs run in the background and the page polls their status.

## Results
| Item | Value |
| --- | --- |
| Encounters found (10 s steps) | 179,075 |
| Convergence check (15 s steps) | 179,074 |
| Edges found by the 60 s first version | 8,132 |
| Sweep time | 16 s on 12 workers |
| Top payloads (neighbours) | DAMPE 115, FLOCK 4G-12 115, ASTROCAST-0404 108 |
| Top debris | FENGYUN 1C DEB 96, COSMOS 2251 DEB 94 |
| Top rocket body | SL-4 R/B 46 |
| Brief speed (Windows) | about 20 s, 21-27 tokens/s |
| Grounded briefs | 3 of 3 test runs |
| Tests passing | 43 |

What "good" means: the 10 s and 15 s counts agree, so the result is converged. The debris leaders are fragments of the 2007 Chinese anti-satellite test and the 2009 Iridium-Cosmos collision, which is what we would expect.

Excerpt from a real Granite brief: "Miss Distance: 4.92 km ... Fragments: 11,259 ... Satellites exposed: 8,943 ... Recommendation: Perform the first burn that meets the target with no new close approach."

## Try it
```
.venv/Scripts/python -m orbitguard.network.run --hours 24
.venv/Scripts/python -m orbitguard.brief.run --primary 25544
LLM_BACKEND=llamacpp LLM_MODEL_PATH=models/llm/granite-3.3-2b-instruct-Q4_K_M.gguf .venv/Scripts/python -m orbitguard.brief.run --primary 25544
.venv/Scripts/python -m legacy.flask_dashboard.run
```
The dashboard serves on port 8080. `LLM_BACKEND` can be `template`, `llamacpp`, or an OpenAI-compatible API.

Code: [orbitguard/network/](../../orbitguard/network/), [orbitguard/brief/](../../orbitguard/brief/), [legacy/flask_dashboard/](../../legacy/flask_dashboard/).

## Limits and honest caveats
- Mass values are assumptions, so scores are a ranking aid, not a measurement.
- The in-step closest approach assumes straight-line motion.
- Granite sometimes numbers list items and can phrase uncertainty loosely. The guard checks numbers, not wording.
- The LLM and dashboard have not yet run on the LinuxONE VM. On the VM the model must be converted to big-endian format (see [vm_runbook.md](../vm_runbook.md)).

## What's next
Phase 6: port to the LinuxONE VM, confirm the footer reads s390x / big, and capture evidence screenshots in `docs/evidence/`.
