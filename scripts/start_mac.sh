#!/usr/bin/env bash
# Start the UI on the Mac (Ollama must be running: the app, or `ollama serve`).
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/encore doctor || true
exec .venv/bin/encore serve --host "${HOST:-127.0.0.1}" --port "${PORT:-8700}"
