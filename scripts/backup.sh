#!/usr/bin/env bash
# 数据备份入口：调用 backend app.operations.backup（create/verify/restore）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${WANWEI_PYTHON:-$ROOT/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON" -m app.operations.backup "$@"
