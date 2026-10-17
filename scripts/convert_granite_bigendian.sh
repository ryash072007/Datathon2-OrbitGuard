#!/usr/bin/env bash
# Convert IBM Granite 3.3 2B Instruct to a big-endian GGUF for s390x (little-endian GGUFs will not load).
# Reference: https://github.com/ggml-org/llama.cpp/blob/master/docs/build-s390x.md
# Run on the VM from the repo root, inside the venv from vm_setup.sh:  bash scripts/convert_granite_bigendian.sh
set -euo pipefail
# Fixed llama.cpp release tag (has Granite 3.x and --bigendian). Override with LLAMA_TAG=... if the tag is missing.
LLAMA_TAG="${LLAMA_TAG:-b11707}"
HF_REPO="ibm-granite/granite-3.3-2b-instruct"
WORK="${WORK:-$HOME/granite_work}"
OUT="models/llm/granite-3.3-2b-instruct-q8_0-be.gguf"
mkdir -p "$WORK" "$(dirname "$OUT")"

if [ -f "$OUT" ]; then
  echo "$OUT already exists, nothing to do"
else
  if [ ! -d "$WORK/llama.cpp" ]; then
    git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
  fi
  python -m pip install -r "$WORK/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt"

  MODEL_DIR="$WORK/granite-hf"
  if [ ! -f "$MODEL_DIR/config.json" ]; then
    if command -v huggingface-cli >/dev/null 2>&1 || python -m pip install "huggingface_hub[cli]" >/dev/null 2>&1; then
      huggingface-cli download "$HF_REPO" --local-dir "$MODEL_DIR"
    else
      echo "huggingface-cli unavailable, falling back to git lfs"
      git lfs install
      git clone "https://huggingface.co/$HF_REPO" "$MODEL_DIR"
    fi
  fi

  python "$WORK/llama.cpp/convert_hf_to_gguf.py" "$MODEL_DIR" --outtype q8_0 --bigendian --outfile "$OUT"
fi

ls -lh "$OUT"
cat <<EOF

Set these before running the brief or dashboard:
  export LLM_BACKEND=llamacpp
  export LLM_MODEL_PATH=$PWD/$OUT
Test:  python -m src.brief.run --primary 25544
EOF
