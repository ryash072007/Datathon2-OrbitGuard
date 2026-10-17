#!/usr/bin/env bash
# LinuxONE VM setup: clone/pull, venv (sees system ML libs), install only missing pins, run tests.
#   REPO_URL=<git url> bash scripts/vm_setup.sh      (run from inside the repo to just update it)
set -euo pipefail
REPO_URL="${REPO_URL:-}"
if [ -f requirements.txt ] && [ -d .git ]; then
  git pull --ff-only || echo "warning: git pull failed, continuing with the current checkout"
elif [ -n "$REPO_URL" ]; then
  git clone "$REPO_URL" datathon2 && cd datathon2
else
  echo "Run inside the repo clone, or set REPO_URL=https://github.com/<you>/<repo>.git" >&2; exit 1
fi

# Security: private keys must never sit inside the repo directory (they could be committed or baked into an image).
pems="$(find . -path ./.git -prune -o -path ./.venv -prune -o \( -name '*.pem' -o -name '*.key' -o -name 'id_rsa*' -o -name 'id_ed25519*' \) -print 2>/dev/null || true)"
if [ -n "$pems" ]; then
  echo "WARNING: key files inside the repo directory, move them out (e.g. ~/.ssh) and never commit them:" >&2
  echo "$pems" >&2
fi

python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --quiet --upgrade pip || true

# Install only requirements whose package is not already importable (never replace the VM's tuned wheels).
python - <<'PY'
import importlib.metadata as md, re, subprocess, sys

def reqs():
    for line in open("requirements.txt", encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            yield line, re.split(r"[=<>!~ ]", line)[0]

missing = []
for line, name in reqs():
    try:
        md.version(name)
    except md.PackageNotFoundError:
        missing.append(line)
if missing:
    print("installing:", " ".join(missing))
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
else:
    print("nothing to install: all requirements already present")
# sgp4 has no s390x wheel: the pure-Python fallback is ~70x slower, so build the C extension.
from importlib import reload
import sgp4.api
if not sgp4.api.accelerated:
    print("sgp4 not accelerated: rebuilding from source")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps",
                           "--no-binary=sgp4", "sgp4"])
    print("re-run to confirm: python -c 'from sgp4.api import accelerated; print(accelerated)'")
print(f"\n{'package':<14}{'pinned':<14}installed")
for line, name in reqs():
    pin = line.split("==")[1] if "==" in line else "(any)"
    try:
        have = md.version(name)
    except md.PackageNotFoundError:
        have = "MISSING"
    print(f"{name:<14}{pin:<14}{have}" + ("" if pin in ("(any)", have) else "   <-- differs"))
try:
    print(f"{'llama_cpp':<14}{'(image)':<14}{md.version('llama_cpp_python')}")
except md.PackageNotFoundError:
    print(f"{'llama_cpp':<14}{'(image)':<14}not installed (template brief only)")
PY

python -c "import sys,platform;print('machine:', platform.machine(), sys.byteorder)"
python -m pytest tests -q
