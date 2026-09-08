#!/bin/bash
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

# guest_build.sh — 在麒麟 guest 上构建桌面 deb/rpm 包（免 apt，用户态 node）
set -e
export PATH="$HOME/opt/node-v22/bin:$PATH"
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1)' \
  || { echo "Node.js 22.12+ is required; run guest_setup2.sh first" >&2; exit 1; }
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
