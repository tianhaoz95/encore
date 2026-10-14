#!/usr/bin/env bash
# Start ComfyUI (:8188) and the encore worker (:8100) on the DGX Spark, LAN-visible.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OPT:=$HOME/encore-opt}"
(cd "$OPT/ComfyUI" && .venv/bin/python main.py --listen 0.0.0.0 --port 8188 > "$OPT/comfyui.log" 2>&1 &)
exec .venv/bin/encore-worker --config worker.yaml --host 0.0.0.0 --port 8100
