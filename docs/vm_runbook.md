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
5. **LLM brief**: `python -m src.brief.run --primary 25544`. Expect backend `llamacpp` and a grounded result.
   On error, use `LLM_BACKEND=template` and say so.
6. **Benchmark**: `python -m src.screen.run --primary 25544 --target-km 10 --benchmark`.
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
