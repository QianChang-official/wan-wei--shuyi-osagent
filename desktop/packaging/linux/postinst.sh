#!/bin/sh
# postinst — 枢忆·花朝 deb/rpm 安装后脚本
# 遵循麒麟桌面软件规范：刷新 desktop 数据库与图标缓存
set -e

if [ -x /usr/bin/update-desktop-database ]; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# Electron 沙箱所需的 chrome-sandbox 权限（deb/rpm 安装时确保 setuid）
SANDBOX="/opt/wanwei-shuyi-desktop/chrome-sandbox"
if [ -f "$SANDBOX" ]; then
  chown root:root "$SANDBOX" 2>/dev/null || true
  chmod 4755 "$SANDBOX" 2>/dev/null || true
fi

# 可选 systemd --user 服务文件：安装到系统目录，方便高级用户用 systemctl 管理
SERVICE_SRC="/opt/wanwei-shuyi-desktop/systemd/wanwei-shuyi-desktop.service"
if [ -f "$SERVICE_SRC" ]; then
  mkdir -p /etc/systemd/user
  cp -f "$SERVICE_SRC" /etc/systemd/user/wanwei-shuyi-desktop.service
  if [ -x /usr/bin/systemctl ]; then
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
fi

exit 0

