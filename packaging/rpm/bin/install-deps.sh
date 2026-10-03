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

#!/bin/sh
# install-deps.sh — 宛委·枢忆 RPM 安装后脚本：自动从网络下载全部 Python 依赖。
#
# 行为：
#   1. 在应用目录创建 venv（发行版缺 ensurepip 时自动降级 --without-pip）；
#   2. venv 内无 pip 时，从镜像站下载官方 pip wheel 自举（zipapp 方式）；
#   3. pip install -r requirements.txt，默认清华镜像，失败依次回退
#      阿里云镜像与 PyPI 官方源（可用 WANWEI_PIP_INDEX 覆盖）；
#   4. 创建数据目录 /var/lib/wanwei-shuyi；
#   5. 非沙箱（WW_PREFIX 为空）时注册并启动 systemd 服务、刷新图标缓存。
#
# 该脚本幂等：重复执行会复用已就绪的 venv。
# 沙箱验证：WW_PREFIX=/path/to/root bash install-deps.sh（跳过 systemd）。

set -eu

PREFIX="${WW_PREFIX:-}"
APP_DIR="${PREFIX}/opt/apps/wanwei-shuyi"
VENV="${APP_DIR}/venv"
DATA_DIR="${PREFIX}/var/lib/wanwei-shuyi"
REQS="${APP_DIR}/backend/requirements.txt"
LOG_TAG="wanwei-shuyi-install"

log() { printf '[%s] %s\n' "$LOG_TAG" "$*"; }
fail() { printf '[%s] 错误: %s\n' "$LOG_TAG" "$*" >&2; exit 1; }

[ -f "$REQS" ] || fail "未找到依赖清单 $REQS"
command -v python3 >/dev/null 2>&1 || fail "未找到 python3，请先安装 Python 3.10+"

# ── 1. venv ──────────────────────────────────────────────────────────
if [ ! -x "${VENV}/bin/python" ]; then
    log "创建 Python 虚拟环境…"
    if ! python3 -m venv "$VENV" 2>/dev/null; then
        log "ensurepip 不可用，降级为 --without-pip 创建"
        rm -rf "$VENV"
        python3 -m venv --without-pip "$VENV" || fail "venv 创建失败"
    fi
fi

# ── 2. pip 自举 ──────────────────────────────────────────────────────
PIP_INDEXES="${WANWEI_PIP_INDEX:-} https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple https://pypi.org/simple"

fetch() {
    # fetch <url> <out>：仅允许 http/https 且主机为内置镜像白名单
    url="$1"; out="$2"
    case "$url" in
        https://pypi.tuna.tsinghua.edu.cn/*|https://mirrors.aliyun.com/*|https://pypi.org/*|https://files.pythonhosted.org/*) ;;
        *) fail "拒绝从非白名单地址下载: $url" ;;
    esac
    curl -fSL --connect-timeout 10 --max-time 300 -o "$out" "$url"
}

if ! "${VENV}/bin/python" -m pip --version >/dev/null 2>&1; then
    log "venv 内无 pip，从镜像站自举…"
    boot="$(mktemp -d)"
    # find-links 目录只放 wheel —— 索引页若同目录会被 pip 误当链接源解析
    mkdir -p "$boot/whl"
    wheel=""
    for idx in $PIP_INDEXES; do
        [ -n "$idx" ] || continue
        index_html="$boot/pip-index.html"
        if fetch "${idx%/}/pip/" "$index_html" 2>/dev/null; then
            # simple 索引内的相对链接（../../packages/…/pip-x.y.z-py3-none-any.whl#sha256=…）
            href=$(grep -oE 'href="[^"]*pip-[0-9][0-9.]*-py3-none-any\.whl[^"]*"' "$index_html" \
                   | tail -1 | sed -E 's/^href="//; s/"$//; s/#.*$//')
            [ -n "$href" ] || continue
            case "$href" in
                http*) wheel_url="$href" ;;
                /*)    wheel_url="$(printf '%s' "$idx" | sed -E 's|(https?://[^/]+)/.*|\1|')$href" ;;
                ../*)  wheel_url="$(printf '%s' "${idx%/}/pip/" | sed -E 's|(/simple/)[^/]+/$|\1|')$href" ;;
                *)     wheel_url="${idx%/}/pip/$href" ;;
            esac
            wheel="$boot/whl/${wheel_url##*/}"
            if fetch "$wheel_url" "$wheel" 2>/dev/null; then
                break
            fi
            wheel=""
        fi
    done
    [ -n "$wheel" ] || fail "无法下载 pip（请检查网络或设置 WANWEI_PIP_INDEX）"
    log "自举 pip: ${wheel##*/}"
    "${VENV}/bin/python" "$wheel/pip" install --no-index --find-links="$boot/whl" pip \
        || fail "pip 自举安装失败"
    rm -rf "$boot"
fi

# ── 3. 安装依赖（自动网络下载） ───────────────────────────────────────
installed=""
for idx in $PIP_INDEXES; do
    [ -n "$idx" ] || continue
    log "安装依赖（源：$idx）…"
    if "${VENV}/bin/python" -m pip install --disable-pip-version-check -i "$idx" -r "$REQS"; then
        installed=1
        break
    fi
    log "源 $idx 失败，尝试下一镜像"
done
[ -n "$installed" ] || fail "依赖安装失败（所有镜像源均不可用）"

# ── 4. 数据目录 ─────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
chmod 750 "$DATA_DIR" || true

# ── 5. 服务与桌面集成（沙箱跳过） ───────────────────────────────────
if [ -z "$PREFIX" ]; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        install -m 644 "${APP_DIR}/packaging/systemd/wanwei-shuyi.service" /etc/systemd/system/wanwei-shuyi.service
        systemctl daemon-reload || true
        systemctl enable wanwei-shuyi.service || true
        systemctl restart wanwei-shuyi.service || true
        log "服务已启用：http://127.0.0.1:8010/console/"
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q /usr/share/icons/hicolor || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
fi

log "依赖安装完成"
