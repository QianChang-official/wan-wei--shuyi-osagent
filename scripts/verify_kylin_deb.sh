#!/usr/bin/env bash
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

# 麒麟 deb 安装包签名验证脚本
#
# 用途：验证 deb 包的 GPG 签名是否有效，确保安装包来源可信。
# 在信创环境部署前执行，作为供应链安全准入检查。
#
# 前置条件：
#   - 已安装 gpg（GnuPG）
#   - 已导入签名公钥（gpg --import public-key.asc）
#
# 用法：
#   bash scripts/verify_kylin_deb.sh path/to/package.deb
#
# 退出码：
#   0 = 签名有效
#   1 = 签名无效或缺失

set -euo pipefail

DEB="${1:?用法: $0 <package.deb>}"

if [[ ! -f "$DEB" ]]; then
    echo "错误：文件不存在: $DEB" >&2
    exit 1
fi

echo "验证目标: $DEB"

# 检查分离签名文件
SIG="${DEB}.sig"
if [[ ! -f "$SIG" ]]; then
    echo "错误：签名文件不存在: $SIG" >&2
    echo "  该包未签名或签名文件丢失，不应在信创环境部署" >&2
    exit 1
fi

# 验证签名
if gpg --verify "$SIG" "$DEB" 2>&1; then
    echo ""
    echo "✅ 签名验证通过"
    echo "   该包来自可信签名者，可在信创环境部署"
    exit 0
else
    echo ""
    echo "❌ 签名验证失败"
    echo "   该包可能被篡改或来源不可信，禁止部署"
    exit 1
fi
