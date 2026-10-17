# VM runbook (combined OrbitGuard)

Run these in order on the LinuxONE VM from `~/orbitguard`. Note the first failure and move on; the template brief
keeps the demo working without the LLM. Keep SSH keys (`*.pem`) outside the repo directory.

1. **Sync and bootstrap.** From the laptop, run `python3 scripts/linuxone.py sync --host <VM_IP> --key key.pem` (this
   ships the source and the built console). Then on the VM, run `bash scripts/bootstrap-linuxone.sh`. Expect
   `"is_linuxone": true` and no sgp4 assertion error.
2. **Tests.** `.venv/bin/python -m pytest -q`. Expect everything to pass (skips only for artefacts not built yet).
3. **Data.** `.venv/bin/orbitguard fetch-data && .venv/bin/orbitguard prepare-data`. If the VM cannot reach ESA,
   run `fetch-data` on the laptop, then `scripts/linuxone.py sync-data`.
4. **Evidence pipeline** (about 15 minutes; use `tmux`): `bash scripts/run-linuxone-pipeline.sh`. The step log is
   `artifacts/pipeline/status.log`. Use `SKIP_CATALOGUE=1` if CelesTrak is unreachable. Keep `htop` open in a
   second terminal during `screen-live --benchmark` and take a screenshot of it.
5. **Service.** `sudo cp deploy/orbitguard.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now orbitguard`.
   Then, from the laptop: `python3 scripts/linuxone.py tunnel --host <VM_IP> --key key.pem` and open http://localhost:8080.
   The header should read **IBM LinuxONE · s390x**.
6. **Live analysis for the demo.** `.venv/bin/orbitguard brief --primary 25544 --cdm-event 8 --target-km 10`
   (or press **Find and screen** in the Live catalogue tab). Set `TLE_MAX_AGE_H=1e9` to freeze the TLE snapshot
   between takes.
7. **Granite** (optional, 10 to 20 minutes): `bash scripts/convert_granite_bigendian.sh` inside the Jupyter ML
   image (see below). Then set `LLM_BACKEND=llamacpp` and `LLM_MODEL_PATH=.../granite-3.3-2b-instruct-q8_0-be.gguf`
   in the unit file, restart the service, and press **Regenerate** on the brief. It runs at about 1 token/s on
   3 vCPUs, so generate the brief before recording.
8. **NNPA.** Inside the image: `python -m orbitguard nnpa-bench` (add `-e BENCH_HOST=$(hostname)`). This writes
   `artifacts/nnpa/nnpa_bench_<host>.json`, which the Validation page shows.
9. **Container.** `docker build -t orbitguard .` then
   `docker run -d --name orbitguard -p 8080:8080 -v $PWD/artifacts:/app/artifacts orbitguard`.
   Expect `docker ps` to show `healthy`.
10. **Evidence.** `bash scripts/evidence.sh` writes `docs/evidence/<timestamp>/` (lscpu, byte order, NNPA flag,
    containers, speed-up, NNPA, pipeline log, evidence JSON, audit verification). Commit `docs/evidence`.

## Screenshots for the judges (save into `docs/evidence/`)

| Shot | Where |
| --- | --- |
| `lscpu` (s390x, big-endian) and `grep nnpa /proc/cpuinfo` | VM shell |
| `htop` with every core busy during `screen-live --benchmark` | second terminal |
| `docker ps` healthy, `systemctl status orbitguard` | VM shell |
| Header "IBM LinuxONE · s390x" plus the Encounters replay with Act/Wait/Monitor | console |
| Synthetic planning: pair-only creates a hazard with C, OrbitGuard does not | Manoeuvre planning |
| Live catalogue: recommendation, burn table, consequence, Granite brief (grounded badge) | Live catalogue |
| Platform section (NNPA table, speed-up), decision evidence, audit chain intact | Validation |

## What worked on the VM before the merge (z17, 3 vCPU, 8 GB; measured 17 Oct)

These ran in the official Jupyter ML image (the host Python lacks TF/torch/llama_cpp). Shorthand:
`D="sudo docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e TLE_MAX_AGE_H=1e9 -v ~/orbitguard:/work -w /work --entrypoint '' <image>"`.

- **NNPA benchmark** took about 2 minutes. Results: 1.06x at 1k rows, 1.6x at 10k, 2.1x at 100k, 2.7x at 1M (about
  0.41M to 1.10M rows/s); max |dprob| 0.0015.
- **Granite big-endian:** prefetch with `PREPARE_ONLY=1`, then convert. It took about 8 minutes and produced a 2.7 GB q8_0 GGUF.
  Mount a work directory outside the repo (`-v ~/granite_work:/granite_work -e WORK=/granite_work`).
- **Brief:** `backend: llamacpp | grounded: True`, but only about 1 token/s with 3 threads (511 tokens in 523 s).
- **sgp4:** with no s390x wheel the pure-Python fallback made the screener about 70x slower (939 s). The bootstrap
  and Dockerfile now build the C extension.
- Part C (llama.cpp built with zDNN) was skipped for time.
