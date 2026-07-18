#!/bin/bash
# guest_build.sh — 在麒麟 guest 上构建桌面 deb/rpm 包（免 apt，用户态 node）
set -e
export PATH="$HOME/opt/node-v20/bin:$PATH"
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"

cd ~/wanwei
# 拉取源码（幂等）
curl -s -o wanwei-src.tar.gz http://10.0.2.2:8000/dl/wanwei-src.tar.gz
rm -rf app && mkdir -p app
tar -xzf wanwei-src.tar.gz -C app
cd app

echo "== frontend dist =="; ls frontend/console-vue/dist/index.html

cd desktop
echo "== npm install desktop =="
npm install --no-audit --no-fund 2>&1 | tail -5

echo "== electron-builder deb =="
npx electron-builder --linux deb --x64 2>&1 | tail -25

echo "== artifacts =="
ls -la release/ || ls -la dist/ || true
echo BUILD_DONE
