#!/usr/bin/env bash
# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

# 本地单端口启动：只起后端，由后端直出已构建的控制台 dist，默认 127.0.0.1:8010。
#
# 与 scripts/dev.sh 的分工：
#   - run_dev.sh：单端口、生产式形态（后端直出 dist），适合验证打包结果
#   - dev.sh     ：开发式形态（前后端分离 + 热更新），日常开发用这个
#
# 解释器按优先级探测 .venv-agent -> backend/.venv -> .venv -> PATH，
# 并校验 uvicorn 是否真的装上了（只看路径存在会选到半残的 venv）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PYTHON=""
if [[ -n "${WANWEI_PYTHON:-}" ]]; then
  if "$WANWEI_PYTHON" -c 'import uvicorn' 2>/dev/null; then
    PYTHON="$WANWEI_PYTHON"
  else
    echo "WANWEI_PYTHON 指定的解释器缺 uvicorn：$WANWEI_PYTHON" >&2
    exit 1
  fi
else
  for candidate in "$ROOT/.venv-agent/bin/python" "$ROOT/backend/.venv/bin/python" "$ROOT/.venv/bin/python" \
                   "$ROOT/.venv-agent/Scripts/python.exe" "$ROOT/backend/.venv/Scripts/python.exe"; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import uvicorn' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  done
  if [[ -z "$PYTHON" ]] && command -v python3 >/dev/null 2>&1 && python3 -c 'import uvicorn' 2>/dev/null; then
    PYTHON="$(command -v python3)"
  fi
fi
if [[ -z "$PYTHON" ]]; then
  echo "找不到「已安装 uvicorn」的 Python。请先运行 scripts/setup.sh。" >&2
  exit 1
fi

export WANWEI_MEMORY_DB="${WANWEI_MEMORY_DB:-$ROOT/data/runtime/memory.db}"
mkdir -p "$(dirname "$WANWEI_MEMORY_DB")"

# 本地回环请求不应走代理
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

exec "$PYTHON" -m uvicorn app.main:app \
  --app-dir "$ROOT/backend" \
  --host "${WANWEI_HOST:-127.0.0.1}" \
  --port "${WANWEI_PORT:-8010}" \
  --no-proxy-headers
