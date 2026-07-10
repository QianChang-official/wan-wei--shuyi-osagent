#!/usr/bin/env bash
# Production MemoryArena-Lite runner — v0.6
set -e
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"
echo "=== Running Production MemoryArena-Lite (v0.6) ==="
PYTHON="${WANWEI_PYTHON:-$PROJ/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
PYTHONPATH="$PROJ/backend" "$PYTHON" -m app.memory_arena.runner "$@"
