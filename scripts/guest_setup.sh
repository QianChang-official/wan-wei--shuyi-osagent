#!/bin/bash
# guest_setup.sh — 麒麟 guest 环境准备：node、npm、rsync、必要库
set -e
export DEBIAN_FRONTEND=noninteractive
PW='@Qwe123asdf'
SUDO() { echo "$PW" | sudo -S "$@" 2>/dev/null; }

echo "== os =="; cat /etc/os-release | head -3
echo "== arch =="; uname -m
echo "== python =="; python3 --version || true
echo "== node =="; (node -v; npm -v) 2>/dev/null || echo NO_NODE

# 安装 node/npm（麒麟软件源；若已有则跳过）
if ! command -v node >/dev/null 2>&1; then
  SUDO apt-get update -y || true
  SUDO apt-get install -y nodejs npm || SUDO apt-get install -y nodejs
fi
(node -v && npm -v) && echo NODE_READY || echo NODE_FAIL

# 必要运行库（Electron deb 的依赖多数系统自带；补 gtk/xss 等）
SUDO apt-get install -y libgtk-3-0 libnotify4 libnss3 libxss1 libxtst6 xdg-utils python3-venv 2>/dev/null || true

mkdir -p ~/wanwei
echo SETUP_DONE
