from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL is disallowed by the SSRF guard."""


def guard(url: str, *, allow_private: bool = False) -> str:
    """Reject anything but public http(s). Blocks non-web schemes and, unless
    allow_private is set, private / loopback / link-local / reserved addresses
    (including the 169.254.169.254 cloud-metadata endpoint)."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme not allowed: {parsed.scheme or '(none)'}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("missing host")
    if allow_private:
        return url
    for info in _resolve(host):
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeURLError(f"blocked non-public address: {ip}")
    return url


def _resolve(host: str):
    try:
        return socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"cannot resolve host: {host}") from exc
