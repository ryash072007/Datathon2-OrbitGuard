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
# On-chip crypto (CPACF). The audit chain and model fingerprints are SHA-256 through Python's hashlib, which uses
# OpenSSL; on s390x OpenSSL issues the CPACF KIMD instruction when the message-security-assist facility is present.
{ echo "--- message-security-assist facilities in /proc/cpuinfo features"
  grep -m1 -i '^features' /proc/cpuinfo | tr ' ' '\n' | grep -iE '^msa' || echo "no msa flags listed"
  echo "--- icainfo (libica view of CPACF; needs libica-utils)"
  if have icainfo; then icainfo 2>&1 | grep -iE 'sha|aes|function|hw' | head -n 30; else echo "icainfo not installed"; fi
  echo "--- openssl speed sha256 (1 s per size)"
  if have openssl; then openssl speed -seconds 1 -evp sha256 2>&1 | tail -n 3; else echo "openssl not available"; fi
  echo "--- python hashlib sha256 throughput"
  "$PY" - <<'PYEOF' 2>&1
import hashlib, time
buf = b"\0" * (64 << 20)
t0 = time.perf_counter(); hashlib.sha256(buf).hexdigest(); dt = time.perf_counter() - t0
print(f"hashlib.sha256 over 64 MiB: {64 / dt:.0f} MiB/s ({hashlib.sha256().name}, OpenSSL-backed)")
PYEOF
} >"$OUT/cpacf_crypto.txt" 2>&1 || true
"$PY" -m pip list 2>/dev/null | grep -iE '^(numpy|pandas|scipy|scikit-learn|sgp4|flask|joblib|llama[-_]cpp[-_]python|pytest|matplotlib|requests|snapml|tensorflow|ibm[-_]zdnn[-_]plugin|gunicorn) ' >"$OUT/pip_libs.txt" || echo "pip list unavailable" >"$OUT/pip_libs.txt"
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
# IBM Z AI stack artefacts (workload, Snap ML, burn optimiser, Guardian eval); each is optional.
for f in artifacts/ml/workload_evidence.json artifacts/zai/snapml_evidence.json artifacts/optimise/evidence.json artifacts/llm/guard_eval.json; do
  if [ -f "$f" ]; then cp "$f" "$OUT/$(echo "$f" | tr '/' '_')"; else echo "none found: $f" >>"$OUT/missing.txt"; fi
done
f="$(ls -t artifacts/zai/snapml_bench_*.json 2>/dev/null | head -n 1)"
if [ -n "$f" ]; then
  cp "$f" "$OUT/"
  "$PY" -c "
import json,sys
d=json.load(open(sys.argv[1]))
def find(o,p=''):
    if isinstance(o,dict):
        for k,v in o.items():
            if isinstance(v,(int,float)) and 'speedup' in k.lower(): print('  snapml zdnn',p+k,'=',v); return True
            if find(v,p+k+'.'): return True
    elif isinstance(o,list):
        for i,v in enumerate(o):
            if find(v,p+str(i)+'.'): return True
    return False
find(d) or print('  snapml bench: no speedup field in',sys.argv[1])
" "$f" >"$OUT/snapml_speedup.txt" 2>&1 || true
else
  echo "none found: artifacts/zai/snapml_bench_*.json (run orbitguard zai-bench)" >>"$OUT/missing.txt"
fi
"$PY" -m orbitguard audit-verify >"$OUT/audit_verify.txt" 2>&1 || true

echo "Evidence saved to $OUT"
echo "  arch:    $(cat "$OUT/machine_byteorder.txt" 2>/dev/null)"
echo "  cores:   $(cat "$OUT/nproc.txt" 2>/dev/null)"
echo "  nnpa:    $(grep -qi "^nnpa" "$OUT/cpuinfo_features.txt" && echo yes || echo no)"
echo "  SE:      $(cut -d: -f1 "$OUT/secure_execution.txt")"
[ -s "$OUT/snapml_speedup.txt" ] && head -n 1 "$OUT/snapml_speedup.txt"
echo "  files:   $(ls "$OUT" | tr '\n' ' ')"
[ -f "$OUT/missing.txt" ] && cat "$OUT/missing.txt"
exit 0
