#!/bin/sh
set -eu

fail() {
  echo "linux packaging lifecycle test: $*" >&2
  exit 1
}

# 本测试会操作包脚本使用的绝对系统路径，只允许在一次性容器中运行。
# 双重门禁避免维护者误在开发机或目标机上以 root 直接执行。
if [ "${WANWEI_PACKAGING_TEST_CONTAINER:-}" != "1" ]; then
  fail "WANWEI_PACKAGING_TEST_CONTAINER=1 is required"
fi
if [ ! -f /.dockerenv ] && [ ! -f /run/.containerenv ]; then
  fail "a disposable container is required"
fi
if [ "$(id -u)" -ne 0 ]; then
  fail "root is required inside the disposable container"
fi

SCRIPTS_DIR="${WANWEI_PACKAGING_SCRIPTS_DIR:-/package-scripts}"
POSTINST="$SCRIPTS_DIR/postinst.sh"
POSTRM="$SCRIPTS_DIR/postrm.sh"
APP_DIR="/opt/wanwei-shuyi-desktop"
COMMAND_TARGET="$APP_DIR/wanwei-shuyi-desktop"
COMMAND_LINK="/usr/bin/wanwei-shuyi-desktop"
SANDBOX="$APP_DIR/chrome-sandbox"
SERVICE_SRC="$APP_DIR/systemd/wanwei-shuyi-desktop.service"
SERVICE_DST="/etc/systemd/user/wanwei-shuyi-desktop.service"

[ -f "$POSTINST" ] || fail "missing postinst.sh"
[ -f "$POSTRM" ] || fail "missing postrm.sh"
[ ! -e "$COMMAND_LINK" ] && [ ! -L "$COMMAND_LINK" ] \
  || fail "container image unexpectedly owns $COMMAND_LINK"

remove_payload_files() {
  rm -f "$SANDBOX" "$COMMAND_TARGET" "$SERVICE_SRC"
  rmdir "$APP_DIR/systemd" 2>/dev/null || true
}

reset_fixture() {
  rm -f "$COMMAND_LINK" "$SERVICE_DST"
  remove_payload_files
  rmdir "$APP_DIR" 2>/dev/null || true
}
trap reset_fixture EXIT

prepare_payload() {
  mkdir -p "$APP_DIR/systemd"
  : > "$SANDBOX"
  : > "$COMMAND_TARGET"
  chmod 0755 "$COMMAND_TARGET"
  printf '%s\n' '[Unit]' 'Description=Wanwei lifecycle fixture' > "$SERVICE_SRC"
}

assert_owned_link() {
  [ -L "$COMMAND_LINK" ] || fail "command link was not created"
  [ "$(readlink "$COMMAND_LINK")" = "$COMMAND_TARGET" ] \
    || fail "command link has an unexpected target"
}

expect_postinst_failure() {
  if sh "$POSTINST"; then
    fail "postinst unexpectedly replaced a foreign command entry"
  fi
}

# 首次安装、重复配置，以及 deb/rpm 升级参数都必须保留自有入口与服务。
prepare_payload
sh "$POSTINST"
sh "$POSTINST"
assert_owned_link
[ -f "$SERVICE_DST" ] || fail "systemd user service was not installed"
[ "$(stat -c '%U:%G %a' "$SANDBOX")" = 'root:root 4755' ] \
  || fail "Electron sandbox permissions are invalid"
sh "$POSTRM" upgrade
assert_owned_link
[ -f "$SERVICE_DST" ] || fail "deb upgrade removed the service"
sh "$POSTRM" 1
assert_owned_link
[ -f "$SERVICE_DST" ] || fail "rpm upgrade removed the service"

# 包管理器会先删除载荷再执行最终 postrm/postun；空安装目录也应被清理。
remove_payload_files
sh "$POSTRM" 0
[ ! -L "$COMMAND_LINK" ] || fail "final uninstall kept the owned command link"
[ ! -e "$SERVICE_DST" ] || fail "final uninstall kept the copied service"
[ ! -e "$APP_DIR" ] || fail "final uninstall kept an empty application directory"

# 外部符号链接必须导致安装失败，并在最终卸载脚本运行后仍保持不变。
prepare_payload
ln -s /tmp/wanwei-foreign-command "$COMMAND_LINK"
expect_postinst_failure
[ "$(readlink "$COMMAND_LINK")" = /tmp/wanwei-foreign-command ] \
  || fail "foreign command link was changed"
sh "$POSTRM" remove
[ "$(readlink "$COMMAND_LINK")" = /tmp/wanwei-foreign-command ] \
  || fail "postrm removed a foreign command link"
reset_fixture

# 管理员已有的同名普通文件同样不能被覆盖或删除。
prepare_payload
printf '%s\n' foreign-command > "$COMMAND_LINK"
expect_postinst_failure
[ "$(cat "$COMMAND_LINK")" = foreign-command ] \
  || fail "existing command file was changed"
sh "$POSTRM" remove
[ "$(cat "$COMMAND_LINK")" = foreign-command ] \
  || fail "postrm removed an existing command file"

echo "linux-packaging-lifecycle=ok"
