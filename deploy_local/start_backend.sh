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

# 宛委·枢忆 后端本地部署启动脚本（麒麟 V11 Linux 原生 / Windows git-bash）
#
# 用法：
#   bash deploy_local/start_backend.sh              # 前台运行
#   WANWEI_BIND=127.0.0.1 bash ...start_backend.sh  # 仅本机可访问
#
# 默认绑 0.0.0.0 以便局域网内手机 / 安卓模拟器访问 H5 App。
# 认证：X-API-Key，密钥读自 secrets/wanwei_api_key.txt（0600 语义，勿提交）。
#
# 密钥通道说明：
#   - API key 走 WANWEI_API_KEY_FILE 文件路径，不落进程参数；
#   - 加密密钥走 WANWEI_ENCRYPTION_KEY 环境变量 —— 这是后端
#     security/encryption.py 唯一支持的读取通道，因此会出现在
#     /proc/<pid>/environ 中；本地单机演示可接受，多用户生产部署
#     需评估环境变量暴露面（容器环境注入、进程属主隔离等）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Windows(git-bash/MSYS) 下 venv 布局为 Scripts/python.exe，路径需 cygpath
# 转成 Windows 形式供原生 python 读取；麒麟 Linux 原生环境二者都不需要。
IS_MSYS=0
if command -v cygpath >/dev/null 2>&1 && [[ "${OSTYPE:-}" == msys* ]]; then
  IS_MSYS=1
fi
winpath() {
  if [[ "$IS_MSYS" == 1 ]]; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

if [[ "$IS_MSYS" == 1 ]]; then
  PY="$REPO_ROOT/.venv/Scripts/python.exe"
else
  PY="$REPO_ROOT/.venv/bin/python"
fi
[[ -x "$PY" ]] || { echo "!! 找不到 venv python：$PY（先在仓库根建 .venv 并装 backend/requirements.txt）" >&2; exit 1; }

KEY_FILE="$REPO_ROOT/secrets/wanwei_api_key.txt"
ENC_FILE="$REPO_ROOT/secrets/wanwei_encryption_key.txt"
[[ -s "$KEY_FILE" ]] || { echo "!! 缺少 API key 文件：$KEY_FILE" >&2; exit 1; }
[[ -s "$ENC_FILE" ]] || { echo "!! 缺少加密密钥文件：$ENC_FILE（32 字节 base64url Fernet key）" >&2; exit 1; }

export WANWEI_API_KEY_FILE="$(winpath "$KEY_FILE")"
export WANWEI_ENCRYPTION_KEY="$(tr -d '\r\n' < "$ENC_FILE")"
export WANWEI_HOST="${WANWEI_BIND:-0.0.0.0}"
export WANWEI_MEMORY_DB="$(winpath "$REPO_ROOT/data/memory.db")"
export WANWEI_PLATFORM_DIR="$(winpath "$REPO_ROOT/data/platform")"
# 手机端 H5 跨域来源白名单（逗号分隔）。后端默认**不放行**任何跨源请求，
# 通配符 "*" 会被拒绝，所以这里显式列出 H5 静态服务器的来源。
# 未显式传入时，自动探测本机局域网 IPv4 并生成 http://<ip>:3015 与本机回环来源。
H5_PORT="${H5_PORT:-3015}"
if [[ -z "${WANWEI_CORS_ORIGINS:-}" ]]; then
  LAN_IP=""
  if [[ "$IS_MSYS" == 1 ]]; then
    LAN_IP="$(ipconfig 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)"
  else
    LAN_IP="$(ip -4 addr show scope global 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}' | head -1)"
  fi
  ORIGINS="http://127.0.0.1:${H5_PORT},http://localhost:${H5_PORT}"
  [[ -n "$LAN_IP" ]] && ORIGINS="http://${LAN_IP}:${H5_PORT},${ORIGINS}"
  WANWEI_CORS_ORIGINS="$ORIGINS"
fi
export WANWEI_CORS_ORIGINS

PORT="${WANWEI_PORT:-8010}"
mkdir -p "$REPO_ROOT/data/platform"

echo "== 宛委·枢忆 后端 =="
echo "   bind      : ${WANWEI_HOST}:${PORT}"
echo "   api key   : ${KEY_FILE} (len=$(tr -d '\r\n' < "$KEY_FILE" | wc -c))"
echo "   memory db : ${WANWEI_MEMORY_DB}"
echo "   cors      : ${WANWEI_CORS_ORIGINS:-* (default)}"
echo

cd "$REPO_ROOT/backend"
exec "$PY" -m uvicorn app.main:app \
  --host "$WANWEI_HOST" \
  --port "$PORT"
