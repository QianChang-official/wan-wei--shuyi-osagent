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
#
# build-rpm.sh — 在麒麟系统上构建 wanwei-shuyi RPM。
#
# 用法：bash build-rpm.sh /path/to/wanwei-shuyi-1.0.0.tar.gz
# 本机无 rpmbuild 时使用 /opt/rpm-tools（payload 装配的 rpmbuild 4.18）。
# 产物：~/rpmbuild/RPMS/noarch/wanwei-shuyi-1.0.0-1.noarch.rpm

set -euo pipefail

TARBALL="${1:?用法: bash build-rpm.sh <payload.tar.gz>}"
PKG=wanwei-shuyi
VER=1.0.0
TOP="${HOME}/rpmbuild"

# rpmbuild 解析顺序：系统 PATH → /opt/rpm-tools 载荷
if command -v rpmbuild >/dev/null 2>&1; then
    RPMBUILD=rpmbuild
else
    TOOLS=/opt/rpm-tools/root
    RPMBUILD="${TOOLS}/usr/bin/rpmbuild"
    export LD_LIBRARY_PATH="${TOOLS}/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export RPM_CONFIGDIR="${TOOLS}/usr/lib/rpm"
fi
"$RPMBUILD" --version

echo "== 准备 rpmbuild 目录树 =="
mkdir -p "$TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,BUILDROOT}
rm -rf "$TOP/BUILD/${PKG}-${VER}"* "$TOP/BUILDROOT/${PKG}-${VER}"* 2>/dev/null || true

cp "$TARBALL" "$TOP/SOURCES/${PKG}-${VER}.tar.gz"

SPEC_SRC="$(cd "$(dirname "$0")" && pwd)/wanwei-shuyi.spec"
cp "$SPEC_SRC" "$TOP/SPECS/${PKG}.spec"

echo "== 构建 =="
"$RPMBUILD" -bb \
    --define "_topdir $TOP" \
    --define "_dbpath $TOP/.rpmdb" \
    "$TOP/SPECS/${PKG}.spec"

echo "== 产物 =="
find "$TOP/RPMS" -name '*.rpm' -exec ls -la {} \;
