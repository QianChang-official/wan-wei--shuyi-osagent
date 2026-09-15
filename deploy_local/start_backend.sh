#!/usr/bin/env bash
# 宛委·枢忆 后端本地部署启动脚本（Windows git-bash / MSYS）
#
# 用法：
#   bash deploy_local/start_backend.sh              # 前台运行
#   WANWEI_BIND=127.0.0.1 bash ...start_backend.sh  # 仅本机可访问
#
# 默认绑 0.0.0.0 以便局域网内手机 / 安卓模拟器访问 H5 App。
# 认证：X-API-Key，密钥读自 secrets/wanwei_api_key.txt（0600 语义，勿提交）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY="$REPO_ROOT/.venv/Scripts/python.exe"
[[ -x "$PY" ]] || { echo "!! 找不到 venv python：$PY" >&2; exit 1; }

KEY_FILE="$REPO_ROOT/secrets/wanwei_api_key.txt"
ENC_FILE="$REPO_ROOT/secrets/wanwei_encryption_key.txt"
[[ -s "$KEY_FILE" ]] || { echo "!! 缺少 API key 文件：$KEY_FILE" >&2; exit 1; }

export WANWEI_API_KEY_FILE="$(cygpath -w "$KEY_FILE")"
export WANWEI_ENCRYPTION_KEY="$(tr -d '\r\n' < "$ENC_FILE")"
export WANWEI_HOST="${WANWEI_BIND:-0.0.0.0}"
export WANWEI_MEMORY_DB="$(cygpath -w "$REPO_ROOT/data/memory.db")"
export WANWEI_PLATFORM_DIR="$(cygpath -w "$REPO_ROOT/data/platform")"
# 手机端 H5 跨域来源白名单（逗号分隔）。后端默认**不放行**任何跨源请求，
# 通配符 "*" 会被拒绝，所以这里显式列出 H5 静态服务器的来源。
# 未显式传入时，自动探测本机局域网 IP 并生成 http://<ip>:3015 与本机回环来源。
H5_PORT="${H5_PORT:-3015}"
if [[ -z "${WANWEI_CORS_ORIGINS:-}" ]]; then
  LAN_IP="$(ipconfig 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)"
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
