from __future__ import annotations

import time

import httpx

from ._safeurl import guard, resolve_public
from .config import (
    ALLOW_PRIVATE,
    MAX_BYTES,
    MAX_REDIRECTS,
    MAX_RETRIES,
    MIN_INTERVAL,
    PROXIES,
    PROXY,
    PROXY_HOSTS,
    RETRY_BACKOFF,
    USER_AGENT,
)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

_last_seen: dict[str, float] = {}
_proxy_index = 0


class ResponseTooLargeError(Exception):
    """Raised when a response exceeds the byte cap while being read."""


class _CappedStream:
    """Wraps a network stream to abort once more than `limit` bytes are read,
    bounding memory regardless of Content-Length or chunked encoding."""

    def __init__(self, stream, limit: int, seen: int = 0):
        self._stream = stream
        self._limit = limit
        self._seen = seen

    def read(self, max_bytes: int, timeout=None) -> bytes:
        chunk = self._stream.read(max_bytes, timeout)
        self._seen += len(chunk)
        if self._seen > self._limit:
            raise ResponseTooLargeError(f"response exceeds {self._limit} bytes")
        return chunk

    def write(self, buffer, timeout=None):
        self._stream.write(buffer, timeout)

    def close(self):
        self._stream.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        tls = self._stream.start_tls(ssl_context, server_hostname, timeout)
        return _CappedStream(tls, self._limit, self._seen)

    def get_extra_info(self, info):
        return self._stream.get_extra_info(info)


def _guard_request(request: httpx.Request) -> None:
    guard(str(request.url), allow_private=ALLOW_PRIVATE)


def throttle(host: str | None) -> None:
    """Enforce a minimum interval between requests to the same host (politeness)."""
    if MIN_INTERVAL <= 0 or not host:
        return
    wait = MIN_INTERVAL - (time.monotonic() - _last_seen.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_seen[host] = time.monotonic()


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return RETRY_BACKOFF * (2**attempt)


def backoff(resp: httpx.Response, attempt: int) -> None:
    time.sleep(_retry_delay(resp, attempt))


def _host_matches(host: str | None, suffixes: list[str]) -> bool:
    return bool(host) and any(host == s or host.endswith(f".{s}") for s in suffixes)


def _select_proxy(host: str | None = None) -> str | None:
    """The proxy for this host, or None. With WEBFETCH_PROXY_HOSTS set, only
    matching hosts are proxied (others go direct) — 'only if required' routing."""
    global _proxy_index
    if PROXY_HOSTS and not _host_matches(host, PROXY_HOSTS):
        return None
    if PROXIES:
        proxy = PROXIES[_proxy_index % len(PROXIES)]
        _proxy_index += 1
        return proxy
    return PROXY


def _guarded_transport(proxy: str | None) -> httpx.BaseTransport:
    """Transport that caps socket reads and — with no proxy — connects only to the
    guard-validated IP, closing the DNS-rebinding gap. With a proxy the connection
    targets the trusted proxy, so the destination is guarded at the URL level (the
    event hook) rather than IP-pinned. Fails closed: raises if it can't install."""
    transport = httpx.HTTPTransport(proxy=proxy)
    try:
        base_backend = type(transport._pool._network_backend)
    except AttributeError as exc:
        raise RuntimeError(
            "cannot install the SSRF-guarded transport (unsupported httpx/httpcore)"
        ) from exc
    pin = proxy is None

    class _GuardedBackend(base_backend):
        def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            target = resolve_public(host, allow_private=ALLOW_PRIVATE) if pin else host
            stream = super().connect_tcp(
                target,
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )
            return _CappedStream(stream, MAX_BYTES)

    transport._pool._network_backend = _GuardedBackend()
    return transport


def client(
    timeout: float, transport: httpx.BaseTransport | None = None, host: str | None = None
) -> httpx.Client:
    if transport is None:
        transport = _guarded_transport(_select_proxy(host))
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        timeout=timeout,
        transport=transport,
        event_hooks={"request": [_guard_request]},
    )


def get(url: str, timeout: float = 30.0) -> httpx.Response:
    """GET with per-host throttling and retry+backoff on 429/5xx. Each attempt
    uses a fresh client, so a rotating proxy pool changes exit IP on retry."""
    host = httpx.URL(url).host
    resp = None
    for attempt in range(MAX_RETRIES + 1):
        throttle(host)
        with client(timeout, host=host) as http:
            resp = http.get(url)
        if resp.status_code not in RETRY_STATUS or attempt >= MAX_RETRIES:
            break
        backoff(resp, attempt)
    return resp
