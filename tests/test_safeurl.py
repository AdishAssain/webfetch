import socket

import pytest

import webfetch._safeurl as safeurl
from webfetch._safeurl import UnsafeURLError, guard

# All literals below resolve numerically or via /etc/hosts — no network needed.
BLOCKED_URLS = [
    "http://127.0.0.1/",
    "http://127.0.0.1:8080/admin",
    "http://localhost/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",  # AWS/GCP cloud metadata
    "http://169.254.170.2/",  # ECS task metadata
    "http://10.0.0.5/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://0.0.0.0/",
    "http://[fd00::1]/",  # unique-local IPv6
    "http://[fe80::1]/",  # link-local IPv6
    "http://[::ffff:127.0.0.1]/",  # IPv4-mapped loopback
]

BAD_SCHEMES = [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "gopher://example.com/",
    "data:text/plain;base64,AAAA",
    "javascript:alert(1)",
    "ws://example.com/",
    "about:blank",
    "jar:http://example.com!/a",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_blocks_internal_addresses(url):
    with pytest.raises(UnsafeURLError):
        guard(url)


@pytest.mark.parametrize("url", BAD_SCHEMES)
def test_blocks_non_web_schemes(url):
    with pytest.raises(UnsafeURLError):
        guard(url)


def test_missing_host():
    with pytest.raises(UnsafeURLError):
        guard("http:///nohost")


@pytest.mark.parametrize("url", ["https://1.1.1.1/", "http://8.8.8.8/", "https://93.184.216.34/"])
def test_allows_public_ip_literals(url):
    assert guard(url) == url


def test_allow_private_bypass():
    assert guard("http://127.0.0.1/", allow_private=True) == "http://127.0.0.1/"


def test_hostname_resolving_to_private_is_blocked(monkeypatch):
    # DNS-rebinding style: a public-looking name that resolves internally.
    monkeypatch.setattr(
        safeurl.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))]
    )
    with pytest.raises(UnsafeURLError):
        guard("http://sneaky.example.com/")


def test_obfuscated_decimal_ip_blocked_when_resolved(monkeypatch):
    # If the platform resolves 2130706433 -> 127.0.0.1, the guard must catch it.
    monkeypatch.setattr(
        safeurl.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))]
    )
    with pytest.raises(UnsafeURLError):
        guard("http://2130706433/")


def test_public_hostname_allowed(monkeypatch):
    monkeypatch.setattr(
        safeurl.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("1.1.1.1", 0))]
    )
    assert guard("http://good.example.com/") == "http://good.example.com/"


def test_unresolvable_host_blocked(monkeypatch):
    def boom(host, port):
        raise socket.gaierror("nope")

    monkeypatch.setattr(safeurl.socket, "getaddrinfo", boom)
    with pytest.raises(UnsafeURLError):
        guard("http://nonexistent.invalid/")
