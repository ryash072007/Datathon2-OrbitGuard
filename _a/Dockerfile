# Datathon2 dashboard image.
#
# On the LinuxONE VM (default, official image: numpy, pandas, sklearn, llama_cpp_python preinstalled):
#   docker build -t datathon2 .
# Portable fallback (any machine, e.g. Windows/x86 for testing):
#   docker build --build-arg BASE=python:3.12-slim -t datathon2 .
#   docker build --build-arg BASE=python:3.12-slim --build-arg INSTALL_LLAMA=1 -t datathon2 .
# Run (data and models are mounted, never baked in):
#   docker run -d --name datathon2 -p 8080:8080 -v $PWD/data:/app/data -v $PWD/models:/app/models datathon2
ARG BASE=registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
FROM ${BASE}

ARG INSTALL_LLAMA=0
USER root
WORKDIR /app
COPY requirements.txt /app/requirements.txt

# If numpy+pandas+sklearn are already importable (official image) install only the extras,
# so nothing preinstalled is changed. Otherwise install the full pinned list.
RUN set -e; if python -c "import numpy, pandas, sklearn, scipy" 2>/dev/null; then \
        echo "Preinstalled ML stack found: installing extras only"; \
        pip install --no-cache-dir sgp4 flask requests; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi; \
    # sgp4 ships no s390x wheel, so pip picks the pure-Python fallback (~70x slower).
    # Build its C extension from source; fail the build if acceleration is still off.
    pip install --no-cache-dir --force-reinstall --no-deps --no-binary=sgp4 sgp4; \
    python -c "from sgp4.api import accelerated; assert accelerated, 'sgp4 C extension not built'"; \
    if [ "$INSTALL_LLAMA" = "1" ] && ! python -c "import llama_cpp" 2>/dev/null; then \
        pip install --no-cache-dir llama-cpp-python; \
    fi

COPY src/ /app/src/
COPY scripts/ /app/scripts/
RUN mkdir -p /app/data /app/models \
    && (id appuser >/dev/null 2>&1 || useradd --create-home --uid 10001 appuser) \
    && chown -R appuser /app
USER appuser

ENV PORT=8080 DATA_DIR=/app/data PYTHONUNBUFFERED=1 LLM_BACKEND=template
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/status'%os.environ.get('PORT','8080'),timeout=4)" || exit 1
CMD ["python", "-m", "src.app.run"]
