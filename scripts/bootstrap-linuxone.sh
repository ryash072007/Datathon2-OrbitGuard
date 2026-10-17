#!/usr/bin/env bash
# Run on the Ubuntu LinuxONE VM. Native s390x packages avoid compiling SciPy.
set -euo pipefail
if [[ "$(uname -m)" != "s390x" ]]; then
  printf '%s\n' 'This bootstrap is intended for Ubuntu LinuxONE (s390x).' >&2
  exit 1
fi
sudo -n apt-get update -qq
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  python3-venv python3-dev build-essential python3-numpy python3-scipy python3-pandas python3-sklearn \
  python3-flask python3-pytest python3-pip gunicorn
python3 -m venv --system-site-packages .venv
# sgp4 has no s390x wheel and pip would silently pick the pure-Python fallback (~70x slower for the
# catalogue screener): build the C extension from source and fail loudly if it is still not accelerated.
.venv/bin/python -m pip install --no-binary=sgp4 'sgp4>=2.22'
.venv/bin/python -c "from sgp4.api import accelerated; assert accelerated, 'sgp4 C extension not built'"
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m orbitguard environment

# Optional: IBM Snap ML (second-opinion trees, zDNN on Telum). Never fatal.
if .venv/bin/python -m pip install 'snapml>=1.16.2'; then
  echo "snapml installed"
else
  echo "WARNING: snapml install failed. zai-fit/zai-eval/zai-bench will be skipped; everything else still works." >&2
fi
if ldconfig -p 2>/dev/null | grep -qi zdnn || ls /usr/lib*/libzdnn* /usr/local/lib*/libzdnn* >/dev/null 2>&1; then
  echo "zDNN library found"
else
  echo "WARNING: zDNN library not found. Snap ML falls back to CPU trees (no Telum offload)." >&2
  echo "  Try: sudo apt install libzdnn0   (package name unverified; or build from https://github.com/IBM/zDNN)" >&2
fi
