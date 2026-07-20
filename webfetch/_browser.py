from __future__ import annotations

import atexit
from urllib.parse import urlparse

from ._safeurl import guard
from .config import ALLOW_PRIVATE, STATE_PATH, USER_AGENT

_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254"}

_playwright = None
_browser = None


def _blocked(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return True
    return (parsed.hostname or "") in _BLOCKED_HOSTS


def _get_browser():
    """Launch Chromium once and reuse it — launching is the expensive part."""
    global _playwright, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        atexit.register(_shutdown)
    return _browser


def _shutdown() -> None:
    global _playwright, _browser
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None


def render(url: str, wait: str | None, auth: bool, timeout: float) -> str:
    guard(url, allow_private=ALLOW_PRIVATE)
    storage = str(STATE_PATH) if auth and STATE_PATH.exists() else None
    # A fresh context per fetch keeps cookies/auth isolated; the browser is reused.
    context = _get_browser().new_context(storage_state=storage, user_agent=USER_AGENT)
    try:
        if not ALLOW_PRIVATE:
            context.route(
                "**/*",
                lambda route: route.abort() if _blocked(route.request.url) else route.continue_(),
            )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        if wait:
            page.wait_for_selector(wait, timeout=timeout * 1000)
        return page.content()
    finally:
        context.close()
