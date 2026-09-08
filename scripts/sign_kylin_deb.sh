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

# 麒麟 deb 安装包 GPG 签名脚本
#
# 用途：对 CI 产出的 unsigned deb 包进行 GPG 签名，生成可分发的签名版本。
# 签名后的包可通过 apt 的 debsig 验证，满足信创环境"来源可信"的准入要求。
#
# 前置条件：
#   - 已安装 gpg（GnuPG）
#   - 已导入签名私钥（见 README 或 1Password/Vault）
#   - 环境变量 WANWEI_SIGNING_KEY 指定签名密钥 ID（指纹或邮箱）
#
# 用法：
#   bash scripts/sign_kylin_deb.sh path/to/package.deb
#
# 产出：
#   - package.deb          （原文件被覆盖为已签名版本）
#   - package.deb.sig      （分离签名，供离线验证）
#   - KYLIN-SIGNATURE-STATUS.txt 更新为 SIGNED

set -euo pipefail

DEB="${1:?用法: $0 <package.deb>}"

if [[ ! -f "$DEB" ]]; then
    echo "错误：文件不存在: $DEB" >&2
    exit 1
fi

if [[ -z "${WANWEI_SIGNING_KEY:-}" ]]; then
    echo "错误：未设置 WANWEI_SIGNING_KEY 环境变量" >&2
    echo "  示例: export WANWEI_SIGNING_KEY='release@wanwei-shuyi.dev'" >&2
    exit 1
fi

# 检查私钥是否可用
if ! gpg --list-secret-keys "$WANWEI_SIGNING_KEY" &>/dev/null; then
    echo "错误：未找到私钥 $WANWEI_SIGNING_KEY" >&2
    echo "  请先导入: gpg --import private-key.asc" >&2
    exit 1
fi

echo "签名目标: $DEB"
echo "签名密钥: $WANWEI_SIGNING_KEY"

# 生成分离签名（.sig 文件）
gpg --detach-sign --armor \
    --local-user "$WANWEI_SIGNING_KEY" \
    --output "${DEB}.sig" \
    "$DEB"

echo "分离签名: ${DEB}.sig"

# 将签名嵌入 deb 包（debsign 方式）
# debsign 是 deb 生态的标准签名工具，通过 .changes 文件工作。
# 对于纯 deb 包（无源码包），使用 dpkg-sig 更直接。
if command -v dpkg-sig &>/dev/null; then
    dpkg-sig --sign builder -k "$WANWEI_SIGNING_KEY" "$DEB"
    echo "dpkg-sig 嵌入签名完成"
else
    echo "提示：dpkg-sig 不可用，仅生成分离签名（.sig）"
    echo "  安装: apt-get install dpkg-sig"
fi

# 更新签名状态标记
STATUS_FILE="$(dirname "$DEB")/KYLIN-SIGNATURE-STATUS.txt"
cat > "$STATUS_FILE" <<EOF
SIGNED
Package: $(basename "$DEB")
Signed-By: $WANWEI_SIGNING_KEY
Signed-At: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Signature: ${DEB}.sig
Verification: gpg --verify ${DEB}.sig ${DEB}
EOF

echo "签名状态已更新: $STATUS_FILE"
echo "验证签名: gpg --verify ${DEB}.sig $DEB"
