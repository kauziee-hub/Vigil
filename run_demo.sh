#!/usr/bin/env bash
# Vigil — one-command demo start (macOS/Linux/Git Bash).
#   ./run_demo.sh            start (seeds DB on first run)
#   ./run_demo.sh --reset    wipe + reseed, then start
#   ./run_demo.sh --mock     force mock payments (offline)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"; FRONTEND="$ROOT/frontend"
if [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then PY="$BACKEND/.venv/Scripts/python.exe"; else PY="$BACKEND/.venv/bin/python"; fi
if [ ! -x "$PY" ]; then
  echo "Creating Python venv..."; python3 -m venv "$BACKEND/.venv"; PY="$BACKEND/.venv/bin/python"
  "$PY" -m pip install -q -r "$BACKEND/requirements.txt"
fi
[ -d "$FRONTEND/node_modules" ] || (cd "$FRONTEND" && npm install --no-audit --no-fund)
(cd "$FRONTEND" && npm run build --silent)
for arg in "$@"; do
  case "$arg" in
    --reset) (cd "$BACKEND" && "$PY" -c "from vigil import db; from vigil.sim import seed; db.connect(); print(seed.seed())") ;;
    --mock) export VIGIL_PAYMENT_PROVIDER=mock ;;
  esac
done
export PYTHONIOENCODING=utf-8
cd "$BACKEND" && exec "$PY" -m vigil.app
