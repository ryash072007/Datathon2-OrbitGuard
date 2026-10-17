#!/usr/bin/env bash
# Full evidence pipeline, run on the LinuxONE VM from ~/orbitguard after
# bootstrap-linuxone.sh and `orbitguard fetch-data && orbitguard prepare-data`.
# Each step's output and timing lands in artifacts/pipeline/. Required steps stop at the first failure;
# the optional IBM Z AI stage at the end (Snap ML, Granite Guardian) only logs SKIP/FAIL.
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
  "decision-fit" "decision-eval" "workload-eval"
  # collision-probability maths and the synthetic stress suite
  "validate-physics" "benchmark-planner --count 50 --runtime-repetitions 20" "optimise-burns synthetic --count 50 --budget 37 --seed 0" "benchmark-runtime"
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

# Optional IBM Z AI stages: a failure or skip is logged but never stops the pipeline or changes its exit code.
opt() { # opt <name> <args...>
  local name=$1; shift
  log "START optional $name"
  local start; start=$(date +%s)
  if .venv/bin/python -m orbitguard "$@" > "artifacts/pipeline/$name.out" 2>&1; then
    log "OK optional $name $(( $(date +%s) - start ))s"
  else
    log "FAIL optional $name rc=$? (non-fatal, see artifacts/pipeline/$name.out)"
  fi
}
if .venv/bin/python -c "import snapml" >/dev/null 2>&1; then
  opt zai-fit zai-fit
  opt zai-eval zai-eval
  opt zai-bench zai-bench
else
  log "SKIP optional zai-fit zai-eval zai-bench (snapml not importable; pip install 'snapml>=1.16.2')"
fi
if [[ -n "${GUARDIAN_MODEL_PATH:-}" ]]; then
  opt guard-eval guard-eval --n 40 --seed 0
else
  log "SKIP optional guard-eval (GUARDIAN_MODEL_PATH not set)"
fi
log "DONE"
