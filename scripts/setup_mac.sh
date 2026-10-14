#!/usr/bin/env bash
# Mac Studio: orchestrator + UI + LLM/VLM/ASR/separation/faces.
# Review before running. Model weights are large: set MODELS_DIR to a big volume.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${LLM_MODEL:=qwen3:32b}"        # 512 GB Studio: qwen3:235b-a22b
: "${VLM_MODEL:=qwen2.5vl:72b}"    # smaller: qwen2.5vl:7b
: "${MODELS_DIR:=$HOME/.ollama/models}"

command -v brew >/dev/null || { echo "install Homebrew first: https://brew.sh"; exit 1; }
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
command -v uv >/dev/null || brew install uv
command -v ollama >/dev/null || brew install --cask ollama

uv venv --python 3.12 .venv
uv pip install -e ".[mac,analysis,dev]"
# optional speaker diarization (needs a HF token once, for the gated weights):
#   uv pip install -e ".[diarization]" && export HF_TOKEN=...

[ -f config.yaml ] || cp config.example.yaml config.yaml
echo "Edit config.yaml: set spark.local to your DGX Spark's hostname/IP."

echo "Pulling local models into $MODELS_DIR (can take a while)…"
OLLAMA_MODELS="$MODELS_DIR" ollama pull "$LLM_MODEL"
OLLAMA_MODELS="$MODELS_DIR" ollama pull "$VLM_MODEL"
echo "Done. Start with: scripts/start_mac.sh"
