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

# 一键拉起「后端 + 前端」本地开发环境（Linux / macOS）。
# 存在理由与 scripts/dev.ps1 相同：消除「该在哪个文件夹执行」的猜测成本。
#
# 用法：
#   bash scripts/dev.sh              # 前后端
#   bash scripts/dev.sh --backend    # 仅后端
#   bash scripts/dev.sh --frontend   # 仅前端
#   BACKEND_PORT=8021 bash scripts/dev.sh

set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1}"

MODE="all"
for arg in "$@"; do
  case "$arg" in
    --backend)  MODE="backend" ;;
    --frontend) MODE="frontend" ;;
    -h|--help)
      sed -n '16,21p' "$0"
      exit 0
      ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend/console-vue"

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "找不到 backend 目录：$BACKEND_DIR" >&2
  exit 1
fi

echo
echo "宛委·枢忆 · 本地开发环境"
echo "仓库根目录：$REPO_ROOT"
echo

# ---------------------------------------------------------------- 解释器探测
# 只认「能import uvicorn」的候选：路径存在不等于依赖齐全，
# 半残的 venv 会让启动失败并给出与真实原因无关的报错。
PYTHON=""
for candidate in "$REPO_ROOT/.venv-agent/bin/python" "$BACKEND_DIR/.venv/bin/python" "$REPO_ROOT/.venv/bin/python" \
                 "$REPO_ROOT/.venv-agent/Scripts/python.exe" "$BACKEND_DIR/.venv/Scripts/python.exe"; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import uvicorn' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  # Git Bash / WSL 下Windows venv 没有 bin/python，退到系统 python3 再验一次
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import uvicorn' 2>/dev/null; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo "找不到「已安装 uvicorn」的 Python 解释器。" >&2
  echo "请先运行 scripts/setup.sh 创建 backend/.venv 并安装依赖。" >&2
  exit 1
fi
echo "Python：$PYTHON ($("$PYTHON" -c 'import platform;print(platform.python_version())'))"

# ---------------------------------------------------------------- 运行时目录
if [[ -z "${WANWEI_MEMORY_DB:-}" ]]; then
  RUNTIME_DIR="$REPO_ROOT/data/runtime"
  mkdir -p "$RUNTIME_DIR"
  export WANWEI_MEMORY_DB="$RUNTIME_DIR/memory.db"
fi

# 本地回环请求不应走代理（http_proxy 会劫持 127.0.0.1，已确认过的坑）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY

PIDS=()

cleanup() {
  if [[ ${#PIDS[@]} -eq 0 ]]; then return; fi
  echo
  echo "正在停止子进程..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      # 杀整个进程组：vite 会派生 esbuild 子进程
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null && kill -KILL -"$pid" 2>/dev/null || true
  done
  PIDS=()
}

# trap EXIT 保证 Ctrl+C / 异常退出都能收干净，不留孤儿占端口
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------- 启动后端
if [[ "$MODE" != "frontend" ]]; then
  BACKEND_LOG="$REPO_ROOT/data/runtime/dev-backend.log"
  mkdir -p "$(dirname "$BACKEND_LOG")"
  echo "启动后端  http://${BIND_ADDRESS}:${BACKEND_PORT}"
  (
    cd "$BACKEND_DIR"
    exec "$PYTHON" -m uvicorn app.main:app \
      --host "$BIND_ADDRESS" --port "$BACKEND_PORT" --no-proxy-headers
  ) >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
  PIDS+=("$BACKEND_PID")

  echo -n "等待后端就绪"
  READY=0
  for _ in $(seq 1 40); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo
      echo "后端进程已退出。日志尾部：" >&2
      tail -n 20 "$BACKEND_LOG" >&2 || true
      exit 1
    fi
    if curl -fsS --noproxy '*' "http://${BIND_ADDRESS}:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      READY=1
      break
    fi
    echo -n "."
    sleep 0.5
  done
  echo
  if [[ "$READY" == "1" ]]; then
    echo "后端就绪  http://${BIND_ADDRESS}:${BACKEND_PORT}/health"
  else
    echo "后端在 20 秒内未就绪，仍继续启动前端。"
  fi
fi

# ---------------------------------------------------------------- 启动前端
if [[ "$MODE" != "backend" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "找不到 npm，跳过前端。请先安装 Node.js 22.12+。"
  else
    if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
      echo "前端依赖未安装，正在执行 npm install..."
      (cd "$FRONTEND_DIR" && npm install)
    fi
    FRONTEND_LOG="$REPO_ROOT/data/runtime/dev-frontend.log"
    mkdir -p "$(dirname "$FRONTEND_LOG")"
    echo "启动前端  http://${BIND_ADDRESS}:${FRONTEND_PORT}/console/"
    # setsid 让 npm 与 vite 同属一个新进程组，cleanup 能整组杀掉
    if command -v setsid >/dev/null 2>&1; then
      (cd "$FRONTEND_DIR" && exec setsid npm run dev -- \
        --host "$BIND_ADDRESS" --port "$FRONTEND_PORT" --strictPort) \
        >"$FRONTEND_LOG" 2>&1 &
    else
      (cd "$FRONTEND_DIR" && exec npm run dev -- \
        --host "$BIND_ADDRESS" --port "$FRONTEND_PORT" --strictPort) \
        >"$FRONTEND_LOG" 2>&1 &
    fi
    PIDS+=("$!")
  fi
fi

# ---------------------------------------------------------------- 收尾
echo
echo "────────────────────────────────────────────"
[[ "$MODE" != "frontend" ]] && echo "API    http://${BIND_ADDRESS}:${BACKEND_PORT}/health"
[[ "$MODE" != "backend" ]]  && echo "控制台 http://${BIND_ADDRESS}:${FRONTEND_PORT}/console/"
echo "日志   $REPO_ROOT/data/runtime/dev-backend.log"
echo "       $REPO_ROOT/data/runtime/dev-frontend.log"
echo "按 Ctrl+C 停止全部进程。"
echo "────────────────────────────────────────────"
echo

if [[ ${#PIDS[@]} -eq 0 ]]; then
  echo "没有任何进程被启动，请检查上方错误提示。" >&2
  exit 1
fi

# 阻塞在前台等待，任一进程退出即整体收场
wait -n
echo "有子进程已退出，正在停止其余进程..." >&2