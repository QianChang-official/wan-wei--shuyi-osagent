#!/bin/bash
# guest_setup.sh — 麒麟 guest 环境准备：node、npm、rsync、必要库
set -e
export DEBIAN_FRONTEND=noninteractive
PW="${WANWEI_VM_PASSWORD:?必须先设置环境变量 WANWEI_VM_PASSWORD（guest 内 wanwei 用户的 sudo 密码），不再硬编码}"
SUDO() { echo "$PW" | sudo -S "$@" 2>/dev/null; }

echo "== os =="; cat /etc/os-release | head -3
echo "== arch =="; uname -m
echo "== python =="; python3 --version || true
echo "== node =="; (node -v; npm -v) 2>/dev/null || echo NO_NODE

node_is_supported() {
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1)' 2>/dev/null
}

# 安装 node/npm（麒麟软件源；若已有则跳过）
if ! node_is_supported; then
  SUDO apt-get update -y || true
  SUDO apt-get install -y nodejs npm || SUDO apt-get install -y nodejs
fi
if ! node_is_supported; then
  echo "NODE_FAIL: Node.js 22.12+ is required; use guest_setup2.sh when the Kylin repository is older." >&2
  exit 1
fi
node -v && npm -v && echo NODE_READY

# 必要运行库（Electron deb 的依赖多数系统自带；补 gtk/xss 等）
SUDO apt-get install -y libgtk-3-0 libnotify4 libnss3 libxss1 libxtst6 xdg-utils python3-venv 2>/dev/null || true

mkdir -p ~/wanwei
echo SETUP_DONE
