#!/bin/sh
# postrm — 枢忆·花朝 deb/rpm 卸载后脚本
set -e

# deb 的最终卸载动作是 remove/purge/disappear，rpm 的最终卸载计数是 0；
# upgrade/1 期间必须保留服务文件，避免旧版本 postrm 删除新版本刚安装的副本。
case "${1:-}" in
  remove|purge|disappear|0|"")
    rm -f /etc/systemd/user/wanwei-shuyi-desktop.service
    COMMAND_TARGET="/opt/wanwei-shuyi-desktop/wanwei-shuyi-desktop"
    COMMAND_LINK="/usr/bin/wanwei-shuyi-desktop"
    if [ -L "$COMMAND_LINK" ] &&
       [ "$(readlink "$COMMAND_LINK")" = "$COMMAND_TARGET" ]; then
      rm -f "$COMMAND_LINK"
    fi
    # rpm 在卸载后可能留下 Electron 载荷的多层空目录。只有确认安装树中
    # 不含任何非目录项时才按深度删除空目录，避免触碰管理员放入的文件、
    # 符号链接或设备节点。精简系统可能没有 find（例如容器基础镜像不带
    # findutils），此时跳过清理而不是让卸载失败。
    APP_DIR="/opt/wanwei-shuyi-desktop"
    if [ -d "$APP_DIR" ] && command -v find >/dev/null 2>&1; then
      if ! find "$APP_DIR" -mindepth 1 ! -type d -print -quit 2>/dev/null | grep -q .; then
        find "$APP_DIR" -depth -type d -empty -delete 2>/dev/null || true
      fi
    fi
    ;;
esac

if [ -x /usr/bin/update-desktop-database ]; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

# 用户数据（~/.config/wanwei-shuyi-desktop）保留，避免误删记忆数据库；
# 如需彻底清理，请用户手动执行：rm -rf ~/.config/wanwei-shuyi-desktop
exit 0
