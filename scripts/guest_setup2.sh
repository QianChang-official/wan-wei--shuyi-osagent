#!/bin/bash
# guest_setup2.sh — 免 apt 的用户态环境准备（麒麟 ostree 防护下可用）
set -e
mkdir -p ~/wanwei ~/opt
cd ~/wanwei

echo "== os =="; cat /etc/os-release | head -2
echo "== arch =="; uname -m
echo "== python =="; python3 --version
python3 -c "import venv; print('VENV_OK')" 2>/dev/null || echo VENV_MISSING

# 用户态安装 Node.js v22.23.2（官方 x64 tarball，不经 apt）
if [ ! -x ~/opt/node-v22/bin/node ]; then
  if [ "$(uname -m)" != "x86_64" ]; then
    echo "guest_setup2.sh 仅支持 Node.js 官方 x64 包；当前架构：$(uname -m)" >&2
    exit 1
  fi

  NODE_ARCHIVE="node-v22.23.2-linux-x64.tar.xz"
  NODE_SHA256="d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307"
  NODE_STAGING="$(mktemp -d "$HOME/opt/.node-v22.XXXXXX")"
  trap 'rm -rf "$NODE_STAGING" "$HOME/wanwei/node.tar.xz"' EXIT

  curl --fail --show-error --location -o node.tar.xz "http://10.0.2.2:8000/dl/$NODE_ARCHIVE"
  printf '%s  %s\n' "$NODE_SHA256" node.tar.xz | sha256sum --check --status -
  tar -xJf node.tar.xz -C "$NODE_STAGING"

  rm -rf "$HOME/opt/node-v22"
  mv "$NODE_STAGING/node-v22.23.2-linux-x64" "$HOME/opt/node-v22"
  rmdir "$NODE_STAGING"
  rm -f node.tar.xz
  trap - EXIT
fi
export PATH="$HOME/opt/node-v22/bin:$PATH"
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1)'
node -v && npm -v && echo NODE_READY

# 配置 npm 国内镜像（离线/慢网兜底）
npm config set registry https://registry.npmmirror.com
echo SETUP_DONE
