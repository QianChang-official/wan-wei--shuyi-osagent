#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${WANWEI_PYTHON:-$ROOT/backend/.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

export WANWEI_MEMORY_DB="${WANWEI_MEMORY_DB:-$ROOT/data/runtime/memory.db}"
mkdir -p "$(dirname "$WANWEI_MEMORY_DB")"

exec "$PYTHON" -m uvicorn app.main:app \
  --app-dir "$ROOT/backend" \
  --host "${WANWEI_HOST:-127.0.0.1}" \
  --port "${WANWEI_PORT:-8010}" \
  --no-proxy-headers
