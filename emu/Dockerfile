# Local LinuxONE (s390x, big-endian) emulator image, run under QEMU via Docker Desktop.
# Mirrors the VM's s390x userland (Ubuntu 24.04) to catch install/endianness problems early.
# Package versions differ from the official image
# registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x (numpy 2.0.2, pandas 3.0.6,
# scipy 1.13.1, scikit-learn 1.9.0, xgboost 3.4.1, torch 2.11.0+cpu, onnx 1.22.0,
# llama_cpp_python 0.3.36), so code must avoid version-specific APIs.
ARG BASE=ubuntu:24.04
FROM --platform=linux/s390x ${BASE}

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip python3-dev build-essential git curl ca-certificates \
        python3-numpy python3-scipy python3-pandas python3-sklearn python3-matplotlib \
        python3-pytest python3-joblib \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY emu/requirements-emu.txt /tmp/requirements-emu.txt
RUN pip install --no-cache-dir -r /tmp/requirements-emu.txt

# xgboost is intentionally NOT installed: no s390x wheel, so pip compiles it from source under QEMU
# (>10 min). Code falls back to sklearn HistGradientBoosting. Uncomment to try anyway:
# RUN pip install --no-cache-dir xgboost || echo "WARN: xgboost unavailable"

WORKDIR /work
CMD ["bash"]
