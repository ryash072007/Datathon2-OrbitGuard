#!/usr/bin/env bash
# Full evidence pipeline, run on the LinuxONE VM from ~/orbitguard after
# bootstrap-linuxone.sh and `orbitguard fetch-data && orbitguard prepare-data`.
# Each step's output and timing lands in artifacts/pipeline/.
set -uo pipefail
cd "$(dirname "$0")/.."
export ORBITGUARD_ROOT=$PWD OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p artifacts/pipeline
log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a artifacts/pipeline/status.log; }
for step in "train" "evaluate" "audit-accuracy" "train-triage" "evaluate-triage" "train-guard" "evaluate-guard" "validate-physics" "benchmark-planner --count 50 --runtime-repetitions 20" "benchmark-runtime"; do
  name=${step%% *}
  log "START $name"
  start=$(date +%s)
  # shellcheck disable=SC2086
  if .venv/bin/python -m orbitguard $step > "artifacts/pipeline/$name.out" 2>&1; then
    log "OK $name $(( $(date +%s) - start ))s"
  else
    status=$?
    log "FAIL $name rc=$status $(( $(date +%s) - start ))s"
    exit "$status"
  fi
done
log "DONE"
