#!/usr/bin/env bash
# 一键环境安装：创建 backend/.venv、安装依赖、构建前端 dist（要求 Python 3.10+、Node 20+、npm 10+）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend/console-vue"
PYTHON="${WANWEI_BOOTSTRAP_PYTHON:-python3}"

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10 or newer is required." >&2
  exit 1
}
command -v node >/dev/null || { echo "Node.js 20 or newer is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm 10 or newer is required." >&2; exit 1; }
node -e 'const major=Number(process.versions.node.split(".")[0]); process.exit(major >= 20 ? 0 : 1)' || {
  echo "Node.js 20 or newer is required." >&2
  exit 1
}
npm --version | awk -F. '{exit ($1 >= 10 ? 0 : 1)}' || {
  echo "npm 10 or newer is required." >&2
  exit 1
}

if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  "$PYTHON" -m venv "$BACKEND/.venv"
fi
VENV_PYTHON="$BACKEND/.venv/bin/python"
mkdir -p "$ROOT/.cache/pip" "$ROOT/.cache/npm" "$ROOT/data/runtime"
PIP_CACHE_DIR="$ROOT/.cache/pip" "$VENV_PYTHON" -m pip install -r "$BACKEND/requirements-dev.txt"
npm_config_cache="$ROOT/.cache/npm" npm --prefix "$FRONTEND" ci
npm_config_cache="$ROOT/.cache/npm" npm --prefix "$FRONTEND" run build
WANWEI_MEMORY_DB="$ROOT/data/runtime/memory.db" PYTHONPATH="$BACKEND" "$VENV_PYTHON" -m app.init_db

echo "Setup complete."
echo "Start:   bash scripts/run_dev.sh"
echo "Console: http://127.0.0.1:8010/console/"
