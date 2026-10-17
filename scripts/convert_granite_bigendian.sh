#!/usr/bin/env bash
# Convert IBM Granite 3.3 2B Instruct to a big-endian GGUF for s390x (little-endian GGUFs will not load).
# Reference: https://github.com/ggml-org/llama.cpp/blob/master/docs/build-s390x.md
# Run from the repo root with the python that has torch + transformers + huggingface_hub (the VM image's
# /opt/venv python, i.e. inside the datathon2 container, or a venv from vm_setup.sh). Idempotent.
#   docker: sudo docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v ~/IBM-Datathon:/work -v ~/granite_work:/granite_work \
#             -e WORK=/granite_work -w /work --entrypoint "" datathon2 bash scripts/convert_granite_bigendian.sh
# Does NOT pip-install anything: torch/transformers/numpy come from the image, and the `gguf` package is taken
# from the llama.cpp checkout (gguf-py) so the converter and the library always match.
set -euo pipefail
# Fixed llama.cpp release tag (has Granite 3.x and --bigendian). Override with LLAMA_TAG=... if the tag is missing.
LLAMA_TAG="${LLAMA_TAG:-b11707}"
HF_REPO="${HF_REPO:-ibm-granite/granite-3.3-2b-instruct}"
WORK="${WORK:-$HOME/granite_work}"
OUT="${OUT:-models/llm/granite-3.3-2b-instruct-q8_0-be.gguf}"
PY="${PYTHON:-python}"
mkdir -p "$WORK" "$(dirname "$OUT")"

if [ -f "$OUT" ]; then
  echo "$OUT already exists, nothing to do"
else
  if [ ! -f "$WORK/llama.cpp/convert_hf_to_gguf.py" ]; then
    rm -rf "$WORK/llama.cpp"
    git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
  fi
  export PYTHONPATH="$WORK/llama.cpp/gguf-py${PYTHONPATH:+:$PYTHONPATH}"
  # The converter imports sentencepiece before checking for tokenizer.model. There is no s390x wheel and Granite 3.x
  # has no tokenizer.model (it uses a GPT-2 BPE vocab), so a stub module is enough: the converter then raises
  # FileNotFoundError and falls back to _set_vocab_gpt2, exactly as with the real package installed.
  if ! "$PY" -c "import sentencepiece" >/dev/null 2>&1; then
    mkdir -p "$WORK/stubs/sentencepiece"
    printf 'class SentencePieceProcessor:
    """stub: Granite has no tokenizer.model"""
' > "$WORK/stubs/sentencepiece/__init__.py"
    export PYTHONPATH="$WORK/stubs:$PYTHONPATH"
  fi

  MODEL_DIR="$WORK/granite-hf"
  if [ ! -f "$MODEL_DIR/.complete" ]; then
    "$PY" - "$HF_REPO" "$MODEL_DIR" <<'PYEOF'
import sys
from huggingface_hub import snapshot_download
# safetensors + tokenizer/config only (skip the duplicated .bin/.gguf files)
snapshot_download(sys.argv[1], local_dir=sys.argv[2],
                  allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "merges.txt", "vocab.json"])
PYEOF
    touch "$MODEL_DIR/.complete"
  fi

  if [ "${PREPARE_ONLY:-0}" = "1" ]; then echo "prepared (clone + download); skipping conversion"; exit 0; fi
  # q8_0 straight from safetensors; the converter reads tensors lazily, so peak RAM stays well below the 8 GB.
  tmp="$OUT.part"
  "$PY" "$WORK/llama.cpp/convert_hf_to_gguf.py" "$MODEL_DIR" --outtype q8_0 --bigendian --outfile "$tmp"
  mv "$tmp" "$OUT"
fi

ls -lh "$OUT"
cat <<EOF

Set these before running the brief or dashboard:
  export LLM_BACKEND=llamacpp
  export LLM_MODEL_PATH=$PWD/$OUT
Test:  python -m orbitguard.brief.run --primary 25544
EOF
