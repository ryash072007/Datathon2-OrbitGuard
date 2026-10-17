# Submission checklist

Status as of 2026-10-18. [x] = done and verified, [ ] = team action needed. Items marked **(pre-merge)** were
verified on the earlier OrbitGuard deployment and do not yet cover the merged system. Re-run them on the merged
build before quoting them. See [JUDGING_GUIDE.md](JUDGING_GUIDE.md) and [ACCURACY_REVIEW.md](ACCURACY_REVIEW.md).

## Build and evidence

- [x] (pre-merge) Full pipeline executed on LinuxONE (s390x): train, evaluate, validate-physics, benchmark-planner, benchmark-runtime.
- [x] (pre-merge) 26/26 tests passed on both macOS arm64 and LinuxONE s390x.
- [x] (pre-merge) systemd service active on the VM, bound to 127.0.0.1:8000, enabled at boot.
- [x] (pre-merge) Live browser smoke test through the SSH tunnel (`frontend/test-results/live-*.png`).
- [x] (pre-merge) `docs/RESULTS.md` generated from LinuxONE artefacts.
- [ ] Deploy the merged build (`python3 scripts/linuxone.py sync ...`, then `bash scripts/bootstrap-linuxone.sh`) and run the test suite on the VM.
- [ ] Run `bash scripts/run-linuxone-pipeline.sh` on the VM, including the optional stages:
  - Snap ML: `pip install 'snapml>=1.16.2'`, confirm `libzdnn` is present, so `zai-fit`, `zai-eval` and `zai-bench` run.
  - Guardian: convert the Q8_0 big-endian GGUF with `MODEL=guardian bash scripts/convert_granite_bigendian.sh`, then
    `export GUARDIAN_MODEL_PATH=$PWD/artifacts/llm/granite-guardian-3.2-3b-a800m-q8_0-be.gguf` so `guard-eval` runs.
    Don't use Q4_K_M (it flagged good and bad briefs alike).
  - Check `artifacts/pipeline/status.log` for every stage; a "SKIP" for zai or guard-eval means that evidence is missing.
- [ ] Run `bash scripts/evidence.sh` and commit `docs/evidence` (lscpu, nnpa flag, `cpacf_crypto.txt`, containers, audit verify).
- [ ] Restart the service after the pipeline, then confirm the Validation tab shows no "missing" card and every card names the LinuxONE host.
- [ ] Update the README "Results" section from the VM outputs (the merge changed the screener and the decision-layer path). Quote only what the artefacts show.

## Required by the guidebook (team)

- [ ] **Complete both prerequisite labs (priority, easy to forget).** The notebooks are in
  https://github.com/linuxone-community-cloud/jupyter-lab-ml. Lab 2 is `Loan_Approval_Demo.ipynb`; Lab 1 is probably
  `Churn_Scikit_PyTorch.ipynb` (confirm on Discord, or run all four notebooks). Keep executed-notebook screenshots as evidence.
- [ ] Create the GitHub repository (public, or private with judge access) and push. Before pushing, run `git status` and confirm that `key.pem`, `artifacts/` and `.venv/` are **not** staged (`.gitignore` covers them).
- [ ] Capture evidence screenshots into `docs/evidence/`:
  - terminal: `uname -m` shows `s390x`, `systemctl status orbitguard`, `cat artifacts/pipeline/status.log`
  - the dashboard header's "IBM LinuxONE s390x" indicator and the "IBM LinuxONE platform use" card
  - `orbitguard zai-bench` output (CPU vs zDNN table, with the backend line)
  - `orbitguard guard-eval` output (numeric guard vs Guardian catch rates)
  - `cpacf_crypto.txt` (msa flags and hashlib throughput)
  - the Ask OrbitGuard panel after a question (tool chips, "Numbers grounded", Guardian badge)
  - the Validation tab's "Where the AI helps, and where it doesn't" cards (Forecasting, Workload, Telum, Burn search, Guard evaluation)
  - the Encounters decision card with the Snap ML second-opinion line
- [ ] Record the 3-minute-or-less video following [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Fill every `{placeholder}` from the VM artefacts first, recount the narration, and check the final duration before uploading.
- [ ] Confirm the README credits list covers every library and dataset used (Snap ML, Granite Guardian, zDNN plugin included).
- [ ] Fill in the submission form: repo link, video link, team name **Datathon2**, title `[Datathon2_IBM Z Datathon 2026 Project]`, event code SSF2026, short description (use the README's first paragraph).
- [ ] Submit with at least 30 minutes of buffer for upload failures.

## Do not

- Do not commit or share `key.pem` or the ESA label file.
- Do not commit `artifacts/`, models or datasets.
- Do not quote numbers that are not in an artefact or in the README's LinuxONE results; name the machine for each.
- Do not describe a CPU run as NNPA / zDNN, and do not claim Secure Execution or pervasive encryption.
- Do not substitute fixture screenshots for LinuxONE evidence.
