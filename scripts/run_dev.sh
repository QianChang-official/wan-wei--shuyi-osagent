#!/usr/bin/env bash
# 本地开发启动：以 backend/.venv（或 WANWEI_PYTHON 指定解释器）运行 uvicorn，默认 127.0.0.1:8010。
# 注意：venv 缺失时回退系统 python3，若报 ModuleNotFoundError 请先运行 scripts/setup.sh。
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
