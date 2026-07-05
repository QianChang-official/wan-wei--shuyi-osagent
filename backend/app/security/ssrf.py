from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse


class SSRFError(ValueError):
    pass


_ALLOWED_SCHEMES = {"http", "https"}

# Default block list. In addition to these networks, loopback/link-local/multicast are rejected.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("ff00::/8"),
]


def _hostname_is_blocked(host: str) -> bool:
    if not host:
        return True
    lower = host.lower()
    if lower in {"localhost", "localhost.localdomain"}:
        return True
    # raw IP
    try:
        addr = ipaddress.ip_address(lower.strip("[]"))
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        pass
    return False


def _resolve_blocked(host: str) -> bool:
    import socket
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # cannot resolve -> allow URL validation to continue; network call will fail naturally
        return False
    for _, _, _, _, sockaddr in info:
        ip = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if any(addr in net for net in _BLOCKED_NETWORKS):
            return True
    return False


def validate_external_url(url: str, *, allowlist: list[str] | None = None) -> str:
    """Validate an external HTTP(S) URL against SSRF block lists.

    Returns the normalized URL if allowed, raises SSRFError otherwise.
    """
    url = (url or "").strip()
    if not url:
        raise SSRFError("URL is empty")
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(f"Scheme '{parsed.scheme}' is not allowed")
    host = parsed.hostname
    if host is None:
        raise SSRFError("URL has no host")
    if allowlist:
        allowed_hosts = {h.lower().strip("/") for h in allowlist}
        if host.lower() in allowed_hosts:
            return url
    if _hostname_is_blocked(host):
        raise SSRFError(f"Host '{host}' is in SSRF block list")
    if _resolve_blocked(host):
        raise SSRFError(f"Resolved IP for host '{host}' is in SSRF block list")
    # Reject URLs containing credentials or fragment in the netloc path (basic hygiene)
    if "@" in (parsed.netloc or ""):
        raise SSRFError("URL must not contain credentials")
    return url


def normalize_api_base(api_base: str) -> str:
    return api_base.rstrip("/")
