from __future__ import annotations

import httpx
import pytest


@pytest.fixture
def http_transport(monkeypatch):
    """Swap the real httpx transport for a MockTransport while keeping the real
    guarded-client config (redirect following + SSRF hook) under test."""

    def install(handler):
        import webfetch._http as h

        real = h.client
        monkeypatch.setattr(
            h,
            "client",
            lambda timeout=30.0: real(timeout, transport=httpx.MockTransport(handler)),
        )

    return install
