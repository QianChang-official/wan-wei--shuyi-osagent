#!/usr/bin/env bash
# 交付验收：安装依赖后运行后端 compileall+pytest、前端双构建摘要比对（可复现性）；venv 缺失时明确报错并提示先跑 setup。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${WANWEI_PYTHON:-$ROOT/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  echo "Python environment not found. Run the documented setup first." >&2
  exit 1
fi

cd "$ROOT"
mkdir -p "$ROOT/tmp"
if [ "${WANWEI_SKIP_INSTALL:-0}" != "1" ]; then
  "$PYTHON" -m pip install -r backend/requirements-dev.txt
  npm --prefix frontend/console-vue ci
fi
"$PYTHON" -m compileall -q backend/app
"$PYTHON" -m pytest --basetemp ./tmp/pytest-verify -p no:cacheprovider
verify_dist="$ROOT/tmp/frontend-verify-dist"
npm --prefix frontend/console-vue run build -- --outDir "$verify_dist"
first="$($PYTHON "$ROOT/scripts/tree_digest.py" "$verify_dist")"
npm --prefix frontend/console-vue run build -- --outDir "$verify_dist"
second="$($PYTHON "$ROOT/scripts/tree_digest.py" "$verify_dist")"
if [ "$first" != "$second" ]; then
  echo "Frontend production build is not reproducible." >&2
  exit 1
fi
if [ "${WANWEI_INCLUDE_ARENA:-0}" = "1" ]; then
  PYTHONPATH="$ROOT/backend" "$PYTHON" -m app.memory_arena.runner --output-dir "$ROOT/tmp/arena-verify"
fi
echo "Delivery verification passed."
