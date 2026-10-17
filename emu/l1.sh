#!/usr/bin/env bash
# Local LinuxONE (s390x) emulator helper. See emu/README.md.
set -euo pipefail
export MSYS_NO_PATHCONV=1
IMAGE="${IMAGE:-datathon2-l1emu}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOSTROOT="$(cd "$ROOT" && (pwd -W 2>/dev/null || pwd))"

usage() {
  echo "Usage: bash emu/l1.sh {check|build|shell|run <cmd...>|test|info}"
  echo "  IMAGE env var overrides the image (default datathon2-l1emu)"
}

cmd="${1:-}"; [ $# -gt 0 ] && shift

dr() {
  local args=(--rm --platform linux/s390x -v "$HOSTROOT:/work" -w /work)
  [ -f "$ROOT/.env" ] && args+=(--env-file "$HOSTROOT/.env")
  [ -t 0 ] && args+=(-it)
  local inner="$*"
  if [ -f "$ROOT/requirements.txt" ]; then
    inner="pip install -q -r requirements.txt && $inner"
  fi
  docker run "${args[@]}" "$IMAGE" bash -c "$inner"
}

case "$cmd" in
  check)
    out="$(docker run --rm --platform linux/s390x ubuntu:24.04 uname -m || true)"
    if [ "$out" = "s390x" ]; then echo "OK: s390x emulation works"; else
      echo "FAIL: got '$out'. Hints:"
      echo "  Docker Desktop: restart it from the Start menu."
      echo "  Linux: docker run --privileged --rm tonistiigi/binfmt --install s390x"
      exit 1
    fi ;;
  build)
    docker build --platform linux/s390x -f "$HOSTROOT/emu/Dockerfile" -t "$IMAGE" "$HOSTROOT" ;;
  shell) dr bash ;;
  run)
    [ $# -gt 0 ] || { usage; exit 1; }
    q=""; for a in "$@"; do q+=" $(printf '%q' "$a")"; done
    dr "$q" ;;
  test)
    if [ -d "$ROOT/tests" ]; then dr python -m pytest tests -q; else echo "no tests/ directory"; fi ;;
  info)
    dr 'uname -m; python --version; python -c "import sys; print(\"byteorder:\", sys.byteorder)"; echo "nproc: $(nproc)"
for m in numpy pandas sklearn xgboost sgp4 flask; do python -c "import $m; print(\"$m\", getattr($m, \"__version__\", \"?\"))" 2>/dev/null || echo "$m missing"; done' ;;
  *) usage; [ -z "$cmd" ] || exit 1 ;;
esac
