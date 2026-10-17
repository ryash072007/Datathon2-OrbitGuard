#!/usr/bin/env bash
# Capture hardware/software evidence for the judges into docs/evidence/<timestamp>/. Never fails on a missing tool.
# Run from anywhere on the VM:  bash scripts/evidence.sh
cd "$(dirname "$0")/.." || exit 0
PY="${PYTHON:-python}"; command -v "$PY" >/dev/null 2>&1 || PY=python3
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="docs/evidence/$TS"; mkdir -p "$OUT"
have() { command -v "$1" >/dev/null 2>&1; }
cap() { # cap <file> <cmd...>
  local f="$1"; shift
  if have "$1"; then "$@" >"$OUT/$f" 2>&1 || true; else echo "$1 not available" >"$OUT/$f"; fi
}

cap uname.txt uname -a
cap lscpu.txt lscpu
{ grep -iE '^(features|vendor_id|cpu MHz|# processors|bogomips)' /proc/cpuinfo | sort -u
  echo "--- accelerator flag check"; grep -io nnpa /proc/cpuinfo | sort -u || echo "no accel flag"
} >"$OUT/cpuinfo_features.txt" 2>&1 || true
"$PY" -c "import sys,platform;print(platform.machine(), sys.byteorder)" >"$OUT/machine_byteorder.txt" 2>&1 || true
cap nproc.txt nproc
cap free.txt free -h
if [ -e /sys/firmware/uv/prot_virt_guest ]; then
  echo "present: prot_virt_guest=$(cat /sys/firmware/uv/prot_virt_guest 2>/dev/null) (IBM Secure Execution guest)"
else
  echo "absent: /sys/firmware/uv/prot_virt_guest (not an IBM Secure Execution guest)"
fi >"$OUT/secure_execution.txt"
"$PY" -m pip list 2>/dev/null | grep -iE '^(numpy|pandas|scipy|scikit-learn|sgp4|flask|joblib|llama[-_]cpp[-_]python|pytest|matplotlib|requests) ' >"$OUT/pip_libs.txt" || echo "pip list unavailable" >"$OUT/pip_libs.txt"
{ have docker && { echo "# docker ps"; docker ps 2>&1 || true; }
  have podman && { echo "# podman ps"; podman ps 2>&1 || true; }
  have docker || have podman || echo "no container runtime found"; } >"$OUT/containers.txt"

# Benchmark and demo timings come from earlier runs (orbitguard screen-live --benchmark; orbitguard nnpa-bench; scripts/demo.py).
DATA="${DATA_DIR:-artifacts/live}/out"
for pat in 'speedup_*.json' 'demo_timings_*.json' 'network_*.json'; do
  f="$(ls -t "$DATA"/$pat 2>/dev/null | head -n 1)"
  if [ -n "$f" ]; then cp "$f" "$OUT/"; else echo "none found: $DATA/$pat (run the benchmark / demo first)" >>"$OUT/missing.txt"; fi
done

f="$(ls -t artifacts/nnpa/nnpa_bench_*.json 2>/dev/null | head -n 1)"
if [ -n "$f" ]; then cp "$f" "$OUT/"; else echo "none found: artifacts/nnpa/nnpa_bench_*.json (run orbitguard nnpa-bench)" >>"$OUT/missing.txt"; fi
for f in artifacts/pipeline/status.log artifacts/ml/evidence.json artifacts/ml/decision_evidence.json artifacts/physics/validation.json; do
  [ -f "$f" ] && cp "$f" "$OUT/$(echo "$f" | tr '/' '_')"
done
"$PY" -m orbitguard audit-verify >"$OUT/audit_verify.txt" 2>&1 || true

echo "Evidence saved to $OUT"
echo "  arch:    $(cat "$OUT/machine_byteorder.txt" 2>/dev/null)"
echo "  cores:   $(cat "$OUT/nproc.txt" 2>/dev/null)"
echo "  nnpa:    $(grep -qi "^nnpa" "$OUT/cpuinfo_features.txt" && echo yes || echo no)"
echo "  SE:      $(cut -d: -f1 "$OUT/secure_execution.txt")"
echo "  files:   $(ls "$OUT" | tr '\n' ' ')"
[ -f "$OUT/missing.txt" ] && cat "$OUT/missing.txt"
exit 0
