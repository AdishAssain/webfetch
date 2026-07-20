from __future__ import annotations

import httpx

from ._safeurl import guard
from .config import ALLOW_PRIVATE, MAX_BYTES, MAX_REDIRECTS, USER_AGENT


def _guard_request(request: httpx.Request) -> None:
    guard(str(request.url), allow_private=ALLOW_PRIVATE)


def client(timeout: float, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """An httpx client that SSRF-guards every request, redirects included.

    The request event hook fires for the initial request and each followed
    redirect, so a public URL that redirects to an internal host is blocked.
    """
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
        resp = http.get(url)
        check_size(resp.headers.get("content-length"))
        return resp


def check_size(content_length: str | None) -> None:
    if content_length and int(content_length) > MAX_BYTES:
        raise ValueError(f"response exceeds {MAX_BYTES} bytes")
