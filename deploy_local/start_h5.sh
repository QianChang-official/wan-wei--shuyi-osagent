#!/usr/bin/env bash
# meoo-app（Taro H5）本地静态服务启动脚本
#
# 用法：
#   bash deploy_local/start_h5.sh          # 直接起静态服务
#   REBUILD=1 bash deploy_local/start_h5.sh  # 先重新构建再起
#
# 端口固定 3015（meoo 沙箱约定，见 meoo-app/AGENTS.md，禁止修改）。
set -euo pipefail

APP_DIR="${MEOO_APP_DIR:-F:/workspace/meoo-app}"
PORT=3015
PY="${PY_BIN:-F:/workspace/wanwei_new/.venv/Scripts/python.exe}"

[[ -d "$APP_DIR" ]] || { echo "!! 找不到 meoo-app：$APP_DIR" >&2; exit 1; }
cd "$APP_DIR"

if [[ "${REBUILD:-0}" == "1" || ! -f dist-web/index.html ]]; then
  echo "== 构建 H5（pnpm build:web）=="
  command -v pnpm >/dev/null || { echo "!! 未找到 pnpm，请先 npm i -g pnpm@9.15.9" >&2; exit 1; }
  [[ -d node_modules ]] || pnpm install
  pnpm build:web
fi

# 校验 console 页确实打进了产物——旧构建缺这页会白屏
if ! grep -rq "pages/console/index" dist-web/js/ 2>/dev/null; then
  echo "!! 警告：dist-web 里找不到 pages/console/index，可能是旧构建。请用 REBUILD=1 重跑。" >&2
fi

echo "== H5 静态服务 =="
echo "   dir  : $APP_DIR/dist-web"
echo "   url  : http://0.0.0.0:$PORT/index.html#/pages/console/index"
echo

cd dist-web
exec "$PY" -m http.server "$PORT" --bind 0.0.0.0
