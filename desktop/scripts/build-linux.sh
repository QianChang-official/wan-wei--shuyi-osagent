#!/bin/sh
# 枢忆·花朝 Linux 构建脚本
# 用法：bash scripts/build-linux.sh [deb|rpm|all]
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-deb}"

cd "$ROOT"

# 1. 安装依赖
echo "[1/3] Installing desktop dependencies..."
if [ ! -d "$ROOT/node_modules" ]; then
  npm install
fi

# 2. 确保前端已构建（业务代码零改动，仅产物）
echo "[2/3] Building Vue console..."
FE_DIR="$ROOT/../frontend/console-vue"
if [ ! -f "$FE_DIR/dist/index.html" ]; then
  cd "$FE_DIR"
  if [ ! -d node_modules ]; then npm install; fi
  npm run build
  cd "$ROOT"
fi

# 3. 生成本地图标（开发机若无图标资源）
echo "[3/3] Ensuring icons..."
if [ ! -f "$ROOT/build/icons/512x512.png" ]; then
  python3 "$ROOT/scripts/generate_icons.py"
fi

# 4. 打包
echo "Building Linux packages (target: $TARGET)..."
case "$TARGET" in
  deb)  npx electron-builder --linux deb ;;
  rpm)  npx electron-builder --linux rpm ;;
  all)  npx electron-builder --linux deb rpm ;;
  *)    echo "Usage: $0 {deb|rpm|all}"; exit 1 ;;
esac

echo "Done. Artifacts: $ROOT/release/"
