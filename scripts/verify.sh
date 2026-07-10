#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${WANWEI_PYTHON:-$ROOT/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  echo "Python environment not found. Run the documented setup first." >&2
  exit 1
fi

cd "$ROOT"
if [ "${WANWEI_SKIP_INSTALL:-0}" != "1" ]; then
  "$PYTHON" -m pip install -r backend/requirements-dev.txt
  npm --prefix frontend/console-vue ci
fi
"$PYTHON" -m compileall -q backend/app
"$PYTHON" -m pytest --basetemp ./tmp/pytest-verify -p no:cacheprovider
before="$($PYTHON "$ROOT/scripts/tree_digest.py" "$ROOT/frontend/console-vue/dist")"
npm --prefix frontend/console-vue run build
after="$($PYTHON "$ROOT/scripts/tree_digest.py" "$ROOT/frontend/console-vue/dist")"
if [ "$before" != "$after" ]; then
  echo "Frontend production build is not reproducible." >&2
  exit 1
fi
if [ "${WANWEI_INCLUDE_ARENA:-0}" = "1" ]; then
  PYTHONPATH="$ROOT/backend" "$PYTHON" -m app.memory_arena.runner --output-dir "$ROOT/tmp/arena-verify"
fi
echo "Delivery verification passed."
