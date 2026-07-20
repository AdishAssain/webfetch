from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL is disallowed by the SSRF guard."""


def _is_nonpublic(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve(host: str) -> list:
    try:
        return socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"cannot resolve host: {host}") from exc


def guard(url: str, *, allow_private: bool = False) -> str:
    """Reject anything but public http(s). Blocks non-web schemes and, unless
    allow_private is set, any host that resolves to a private / loopback /
    link-local / reserved address (including 169.254.169.254)."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme not allowed: {parsed.scheme or '(none)'}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("missing host")
    if allow_private:
        return url
    for info in _resolve(host):
        if _is_nonpublic(ipaddress.ip_address(info[4][0])):
            raise UnsafeURLError(f"blocked non-public address: {info[4][0]}")
    return url


def resolve_public(host: str, *, allow_private: bool = False) -> str:
    """Resolve host to a single validated IP, raising if it is non-public.

    Used to pin the connection to the exact address that was validated, closing
    the DNS-rebinding gap between validation and connect.
    """
    ip = _resolve(host)[0][4][0]
    if not allow_private and _is_nonpublic(ipaddress.ip_address(ip)):
        raise UnsafeURLError(f"blocked non-public address: {ip}")
    return ip
