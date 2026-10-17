#!/usr/bin/env bash
# Full evidence pipeline, run on the LinuxONE VM from ~/orbitguard after
# bootstrap-linuxone.sh and `orbitguard fetch-data && orbitguard prepare-data`.
# Each step's output and timing lands in artifacts/pipeline/. Stops at the first failure.
#   SKIP_CATALOGUE=1  run only the ESA / synthetic steps (no CelesTrak download)
set -uo pipefail
cd "$(dirname "$0")/.."
export ORBITGUARD_ROOT=$PWD OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p artifacts/pipeline
log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a artifacts/pipeline/status.log; }
steps=(
  # historical ESA forecasting: frozen model, sealed labels, audits
  "train" "evaluate" "audit-accuracy" "train-triage" "evaluate-triage" "train-guard" "evaluate-guard"
  # Act / Wait / Monitor decision layer (rules + calibrated P(high) + quantile interval)
  "decision-fit" "decision-eval"
  # collision-probability maths and the synthetic stress suite
  "validate-physics" "benchmark-planner --count 50 --runtime-repetitions 20" "benchmark-runtime"
)
if [[ "${SKIP_CATALOGUE:-0}" != "1" ]]; then
  steps+=(
    # real CelesTrak catalogue: validated-Pc screening with parallel speed-up, break-up validation,
    # super-spreader network and the Pc-vs-harm survey
    "screen-live --primary 25544 --days 3 --target-km 10 --benchmark"
    "validate-breakup" "network --hours 24" "consequence --survey 20 --seed 0"
  )
fi
for step in "${steps[@]}"; do
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
