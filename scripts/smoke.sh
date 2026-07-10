#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${WANWEI_PYTHON:-$ROOT/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

exec "$PYTHON" "$ROOT/scripts/smoke.py" \
  --base-url "${WANWEI_BASE_URL:-http://127.0.0.1:8010}" \
  --api-key "${WANWEI_API_KEY:-wanwei-dev-key}" "$@"
