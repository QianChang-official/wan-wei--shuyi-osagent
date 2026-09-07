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

from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse


class SSRFError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 显式信任主机白名单（单一事实源）
# ---------------------------------------------------------------------------
# fake-ip DNS 代理（Clash 系等）会把公网域名解析到 198.18.0.0/15 等保留段，
# 被 pinned-IP 防护按设计拦截。确属显式信任的主机可用环境变量按精确主机名
# 放行；本函数是全仓唯一解析入口，所有外呼路径（模型网关、providers 写入/
# 探测/OAuth、automation http 步骤、MCP 远程传输、系统服务下载/转写）均应
# 经它合并白名单，保证「能连的主机也配得进、跑得动」的同一口径。
# 仅限列出的精确主机：其余域名的 DNS 重绑定防护不受影响。
_SSRF_EXTRA_HOSTS_ENV = "WANWEI_SSRF_EXTRA_ALLOWED_HOSTS"
_SSRF_LEGACY_HOSTS_ENV = "WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST"


def extra_allowed_hosts() -> list[str]:
    """读取显式信任主机白名单（推荐名 + 历史名合并去重，保序）。"""
    merged: list[str] = []
    for env_name in (_SSRF_EXTRA_HOSTS_ENV, _SSRF_LEGACY_HOSTS_ENV):
        raw = os.getenv(env_name, "").strip()
        if raw:
            merged.extend(h.strip() for h in raw.split(",") if h.strip())
    return list(dict.fromkeys(merged))


_ALLOWED_SCHEMES = {"http", "https"}

# Default block list. In addition to these networks, loopback/link-local/multicast are rejected.
# Security hotspot review (v0.9.6.1): Intentional non-configurable SSRF denylist
# constants; making them configurable would weaken default security. These are
# RFC-reserved / private / loopback / link-local / CGNAT / multicast / reserved
# ranges that must always be rejected by default. Do NOT move them into env vars
# or runtime config. Per-deployment exceptions go through the explicit `allowlist`
# parameter of validate_external_url() (exact-host match), never by editing this list.
_BLOCKED_NETWORKS = [  # NOSONAR (intentional hardcoded security denylist)
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("ff00::/8"),
    # IPv6 过渡机制中内嵌 IPv4 的形式（NAT64 / 6to4 / IPv4-compatible）：
    # 这些地址在连接时会解包为内嵌的 IPv4 地址，若不拦截可绕过上方全部
    # IPv4 黑名单直连回环/内网（校验时看是无害公网 IPv6，连接时变内网 IPv4）。
    ipaddress.ip_network("64:ff9b::/96"),   # NAT64 (RFC 6052)
    ipaddress.ip_network("64:ff9b:1::/48"), # 本地-use NAT64 (RFC 8215)
    ipaddress.ip_network("2002::/16"),      # 6to4 (RFC 7526, 已弃用但仍可用)
    ipaddress.ip_network("::/96"),          # IPv4-compatible (已弃用)
    ipaddress.ip_network("::ffff:0:0:0/96"),  # IPv4-translated (RFC 2765/6145)
    ipaddress.ip_network("2001::/32"),      # Teredo (IPv4 异或嵌入，整段保留)
]


def _hostname_is_blocked(host: str) -> bool:
    if not host:
        return True
    lower = host.lower()
    if lower in {"localhost", "localhost.localdomain"}:
        return True
    # raw IP
    try:
        # 归一化所有 IPv6 内嵌 IPv4 的形式（mapped/NAT64/6to4/compatible）
        # 再比对黑名单，避免「校验时是公网 IPv6、连接时解包成内网 IPv4」的绕过。
        addr = _normalise_ip(ipaddress.ip_address(lower.strip("[]")))
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        pass
    return False



def _normalise_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(addr, ipaddress.IPv6Address):
        # IPv4-mapped (::ffff:a.b.c.d)
        if addr.ipv4_mapped:
            return addr.ipv4_mapped
        # NAT64 (64:ff9b::a.b.c.d, RFC 6052)：末 32 位即内嵌 IPv4
        if addr in ipaddress.ip_network("64:ff9b::/96"):
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        # 本地-use NAT64 (64:ff9b:1::/48, RFC 8215)：末 32 位即内嵌 IPv4
        if addr in ipaddress.ip_network("64:ff9b:1::/48"):
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        # IPv4-translated (::ffff:0:a.b.c.d, RFC 2765/6145)：末 32 位即内嵌 IPv4
        if addr in ipaddress.ip_network("::ffff:0:0:0/96"):
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        # 6to4 (2002:a.b.c.d::, RFC 7526)：第 2-5 字节即内嵌 IPv4
        if addr in ipaddress.ip_network("2002::/16"):
            return ipaddress.IPv4Address((int(addr) >> 80) & 0xFFFFFFFF)
        # IPv4-compatible (::a.b.c.d，已弃用但仍可能被构造)；:: 全零不解包
        if addr in ipaddress.ip_network("::/96") and int(addr) != 0:
            return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = _normalise_ip(ipaddress.ip_address(ip.strip("[]")))
    except ValueError:
        return True
    return any(addr in net for net in _BLOCKED_NETWORKS)


def _resolve_ips(host: str) -> list[str]:
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        return [str(_normalise_ip(addr))]
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SSRFError(f"Host '{host}' cannot be resolved") from exc
    ips: list[str] = []
    for _, _, _, _, sockaddr in info:
        ip = sockaddr[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise SSRFError(f"Host '{host}' cannot be resolved")
    return ips


def _resolve_blocked(host: str) -> bool:
    try:
        return any(_ip_is_blocked(ip) for ip in _resolve_ips(host))
    except SSRFError:
        return True


def resolve_external_url(url: str, *, allowlist: list[str] | None = None) -> tuple[str, str]:
    """Validate an external HTTP(S) URL and pin it to one resolved IP."""
    url = (url or "").strip()
    if not url:
        raise SSRFError("URL is empty")
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(f"Scheme '{parsed.scheme}' is not allowed")
    host = parsed.hostname
    if host is None:
        raise SSRFError("URL has no host")
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise SSRFError("URL must not contain credentials")
    allowed = False
    if allowlist:
        allowed_hosts = {h.lower().strip("/") for h in allowlist}
        allowed = host.lower() in allowed_hosts
    if not allowed and _hostname_is_blocked(host):
        raise SSRFError(f"Host '{host}' is in SSRF block list")
    ips = _resolve_ips(host)
    if not allowed and any(_ip_is_blocked(ip) for ip in ips):
        raise SSRFError(f"Resolved IP for host '{host}' is in SSRF block list")
    return url, ips[0]


def validate_external_url(url: str, *, allowlist: list[str] | None = None) -> str:
    """Validate an external HTTP(S) URL against SSRF block lists."""
    normalized, _ = resolve_external_url(url, allowlist=allowlist)
    return normalized

def normalize_api_base(api_base: str) -> str:
    return api_base.rstrip("/")
