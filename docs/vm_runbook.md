# VM runbook (final session)

Do these in order on the LinuxONE VM. Note the first failure and move on; the template brief keeps the demo alive.
Keep SSH keys (`*.pem`) outside the repo directory; `vm_setup.sh` warns if one is inside.

1. **Setup**: `bash scripts/vm_setup.sh` then `source .venv/bin/activate`.
   Expect a pinned-vs-installed table and `machine: s390x big`.
2. **Tests**: `python -m pytest tests -q`. Expect all passed (43 on Windows).
3. **Demo prep**: `python scripts/demo.py --no-serve` (data, decision fit, ISS screen, survey, network, facts).
   Expect a timing summary and `data/out/demo_timings_<host>.json`. Add `--quick` if short on time.
4. **Granite conversion** (10-20 min; use `tmux`): `bash scripts/convert_granite_bigendian.sh`.
   Expect `models/llm/granite-3.3-2b-instruct-q8_0-be.gguf` (about 2.7 GB) and two `export` lines. Run them.
5. **LLM brief**: `python -m orbitguard.brief.run --primary 25544`. Expect backend `llamacpp` and a grounded result.
   On error, use `LLM_BACKEND=template` and say so.
6. **Benchmark**: `python -m orbitguard.catalog.run --primary 25544 --target-km 10 --benchmark`.
   Expect `benchmark workers=N ... speedup=` lines and `data/out/speedup_<host>.json`. Keep `htop` open in a second terminal.
7. **Container (official base)**: `docker build -t datathon2 .` then
   `docker run -d --name datathon2 -p 8080:8080 -v $PWD/data:/app/data -v $PWD/models:/app/models -e LLM_BACKEND=llamacpp -e LLM_MODEL_PATH=/app/models/llm/granite-3.3-2b-instruct-q8_0-be.gguf datathon2`.
   Expect `docker ps` to show `healthy` after about 30 s, and `curl -s -o /dev/null -w "%{http_code}" localhost:8080/` to print 200.
   Without Docker: `python scripts/demo.py --llm`.
8. **Evidence**: `bash scripts/evidence.sh`. Expect `docs/evidence/<timestamp>/` with lscpu, byte order, nproc, benchmark and timings. Then commit `docs/evidence`.
9. **Screenshots** (save into `docs/evidence/`)

   | Shot | Where |
   | --- | --- |
   | `lscpu` showing s390x; byte order `big` | VM shell |
   | `htop` with all cores busy during `--benchmark` | second terminal |
   | Speed-up table (workers vs speedup) | benchmark output |
   | `docker ps` showing `datathon2` healthy | VM shell |
   | Footer: arch s390x, byte order big | bottom of `http://<vm>:8080` |
   | Event picker, risk and Act/Wait/Monitor decision | top panels |
   | Burn options table, consequence bar chart | middle panels |
   | Super-spreaders table and network picture | lower panels |
   | Brief with backend `llamacpp` and grounded badge | brief panel |

## What actually worked on the VM (z17, 3 vCPU, 8 GB; measured 17 Oct)

All commands run in the `datathon2` image (host Python lacks TF/torch/llama_cpp). Shorthand:
`D="sudo docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e DATA_DIR=/work/data -e TLE_MAX_AGE_H=1e9 -v ~/IBM-Datathon:/work -w /work --entrypoint '' datathon2"`.

- **NNPA benchmark**: `$D python -m orbitguard.nnpa.bench` (add `-e BENCH_HOST=$(hostname)` to the docker line so the JSON is named after
  the VM and not the container id). Takes about 2 minutes. Writes `data/out/nnpa_bench_<host>.json` and `models/nnpa_mlp.keras`.
  Result: 1.06x at 1k rows, 1.6x at 10k, 2.1x at 100k, 2.7x at 1M (about 0.41M to 1.10M rows/s); max |dprob| 0.0015.
- **Granite big-endian**: pre-fetch (I/O only) with `PREPARE_ONLY=1`, then convert; about 8 minutes, peak RAM fine:
  `sudo docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e WORK=/granite_work -v ~/IBM-Datathon:/work -v ~/granite_work:/granite_work -w /work --entrypoint '' datathon2 bash scripts/convert_granite_bigendian.sh`
  Output: `models/llm/granite-3.3-2b-instruct-q8_0-be.gguf` (2.7 GB).
- **Brief**: `LLM_BACKEND=llamacpp LLM_MODEL_PATH=/work/models/llm/granite-3.3-2b-instruct-q8_0-be.gguf` gives
  `backend: llamacpp | grounded: True`, but only about 1 token/s with 3 threads (511 tokens took 523 s, prompt 611 tokens).
  `data/out/brief_granite_vm.json` holds it. Pre-generate the brief before recording the video, or lower `max_tokens`.
- **Dashboard container**: `sudo docker run -d --name d2dash --restart unless-stopped --user $(id -u):$(id -g) -p 8080:8080 -e HOME=/tmp -e DATA_DIR=/work/data -e TLE_MAX_AGE_H=1e9 -e LLM_BACKEND=llamacpp -e LLM_MODEL_PATH=/work/models/llm/granite-3.3-2b-instruct-q8_0-be.gguf -v ~/IBM-Datathon:/work -w /work --entrypoint '' datathon2 python -m legacy.flask_dashboard.run`.
  `curl localhost:8080/api/status` returns 200 with `machine: s390x`, `byteorder: big`. Reach it with `ssh -L 8080:localhost:8080 ...`; no firewall change.
- Part C (llama.cpp built with zDNN) was skipped for time.
