#!/usr/bin/env bash
# Production MemoryArena-Lite runner — v0.6
set -e
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"
echo "=== Running Production MemoryArena-Lite (v0.6) ==="
PYTHONPATH="$PROJ/backend" python3 -m app.memory_arena.runner "$@"
