#!/usr/bin/env bash
# Serve the Encore walkthrough site locally.
#   reports/project-walkthrough/script/serve.sh [port]      (default 8765)
#   OPEN=0 serve.sh   to skip opening a browser
set -euo pipefail
SITE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../site" && pwd)"
PORT="${1:-${PORT:-8765}}"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "python3 is required" >&2; exit 1; }

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is busy; pass another: $0 8766" >&2
  exit 1
fi

URL="http://127.0.0.1:$PORT/"
echo "Serving $SITE"
echo "→ $URL   (Ctrl+C to stop)"
if [ "${OPEN:-1}" = "1" ]; then
  ( sleep 1
    if command -v open >/dev/null; then open "$URL"
    elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1
    fi ) &
fi
exec "$PY" -m http.server "$PORT" --bind 127.0.0.1 --directory "$SITE"
