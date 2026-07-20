from __future__ import annotations

import httpx

from ._safeurl import guard, resolve_public
from .config import ALLOW_PRIVATE, MAX_BYTES, MAX_REDIRECTS, USER_AGENT


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


def _guarded_transport() -> httpx.BaseTransport | None:
    """Transport that (1) connects only to the IP the guard validated — reusing
    that resolution closes the DNS-rebinding gap between check and connect — and
    (2) caps the bytes read from the socket. Returns None (event-hook guard only)
    if httpcore isn't shaped as expected."""
    try:
        transport = httpx.HTTPTransport()
        base_backend = type(transport._pool._network_backend)

        class _GuardedBackend(base_backend):
            def connect_tcp(
                self, host, port, timeout=None, local_address=None, socket_options=None
            ):
                ip = resolve_public(host, allow_private=ALLOW_PRIVATE)
                stream = super().connect_tcp(
                    ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
                return _CappedStream(stream, MAX_BYTES)

        transport._pool._network_backend = _GuardedBackend()
        return transport
    except Exception:
        return None


def client(timeout: float, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """An httpx client that SSRF-guards every request (redirects included) at the
    URL level, and pins connections to the validated IP + caps reads at the
    socket level."""
    if transport is None:
        transport = _guarded_transport()
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        timeout=timeout,
        transport=transport,
        event_hooks={"request": [_guard_request]},
    )


def get(url: str, timeout: float = 30.0) -> httpx.Response:
    with client(timeout) as http:
        return http.get(url)
