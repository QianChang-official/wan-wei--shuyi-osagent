#!/bin/sh
# postrm — 枢忆·花朝 deb/rpm 卸载后脚本
set -e

if [ -x /usr/bin/update-desktop-database ]; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# 用户数据（~/.config/wanwei-shuyi-desktop）保留，避免误删记忆数据库；
# 如需彻底清理，请用户手动执行：rm -rf ~/.config/wanwei-shuyi-desktop
exit 0
