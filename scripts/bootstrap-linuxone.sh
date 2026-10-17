#!/usr/bin/env bash
# Run on the Ubuntu LinuxONE VM. Native s390x packages avoid compiling SciPy.
set -euo pipefail
if [[ "$(uname -m)" != "s390x" ]]; then
  printf '%s\n' 'This bootstrap is intended for Ubuntu LinuxONE (s390x).' >&2
  exit 1
fi
sudo -n apt-get update -qq
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  python3-venv python3-numpy python3-scipy python3-pandas python3-sklearn \
  python3-flask python3-pytest python3-pip gunicorn
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m orbitguard environment
