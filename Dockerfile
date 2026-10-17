# OrbitGuard console + API image.
#
# On the LinuxONE VM (default base: the official Community Cloud Jupyter ML image, which already has numpy,
# pandas, scikit-learn, TensorFlow + ibm-zdnn-plugin and llama_cpp_python built for s390x):
#   docker build -t orbitguard .
# Portable fallback (any machine, e.g. x86 for testing):
#   docker build --build-arg BASE=python:3.12-slim -t orbitguard .
# Run (artifacts and the Granite model are mounted, never baked in):
#   docker run -d --name orbitguard -p 8080:8080 -v $PWD/artifacts:/app/artifacts -v $PWD/models:/app/models \
#     -e LLM_BACKEND=llamacpp -e LLM_MODEL_PATH=/app/models/llm/granite-3.3-2b-instruct-q8_0-be.gguf orbitguard
ARG BASE=registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest

# ---- console: the official node image is multi-arch (includes s390x)
FROM node:20-bookworm-slim AS console
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- API, models and scientific stack
FROM ${BASE}
USER root
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY orbitguard/ /app/orbitguard/

# If the ML stack is already importable (official image) install only what is missing, so nothing tuned for
# s390x is replaced. sgp4 ships no s390x wheel: build its C extension (pure Python is ~70x slower) and fail
# the build if acceleration is still off.
RUN set -e; \
    if python -c "import numpy, pandas, sklearn, scipy" 2>/dev/null; then \
        pip install --no-cache-dir flask gunicorn threadpoolctl joblib; \
    else \
        pip install --no-cache-dir "numpy<3" "pandas<4" "scipy<2" "scikit-learn<2" joblib threadpoolctl flask gunicorn; \
    fi; \
    pip install --no-cache-dir --force-reinstall --no-deps --no-binary=sgp4 "sgp4>=2.22"; \
    python -c "from sgp4.api import accelerated; assert accelerated, 'sgp4 C extension not built'"; \
    pip install --no-cache-dir --no-deps --no-build-isolation -e .

COPY --from=console /ui/dist /app/frontend/dist
COPY scripts/ /app/scripts/
RUN mkdir -p /app/artifacts /app/models \
    && (id appuser >/dev/null 2>&1 || useradd --create-home --uid 10001 appuser) \
    && chown -R appuser /app
USER appuser

ENV ORBITGUARD_ROOT=/app PORT=8080 PYTHONUNBUFFERED=1 LLM_BACKEND=template \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 IN_DOCKER=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/platform',timeout=4)" || exit 1
CMD ["python", "-m", "gunicorn", "--workers", "1", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:8080", "orbitguard.wsgi:app"]
