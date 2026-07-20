from __future__ import annotations

import atexit
from urllib.parse import urlsplit

from ._http import _select_proxy
from ._safeurl import UnsafeURLError, guard
from .config import ALLOW_PRIVATE, STATE_PATH, USER_AGENT

_playwright = None
_browser = None


def _allowed(url: str) -> bool:
    """Full resolver guard (not a literal denylist) applied to every browser
    request, so a rendered page can't reach private IPs via a subresource, a
    redirect, or a public host that resolves internally."""
    try:
        guard(url, allow_private=False)
    except UnsafeURLError:
        return False
    return True


def guarded_context(context) -> None:
    """Abort any browser request (subresource or redirect) to a non-public host."""
    context.route(
        "**/*",
        lambda route: route.continue_() if _allowed(route.request.url) else route.abort(),
    )


def _pw_proxy(host: str | None = None) -> dict | None:
    """Playwright proxy dict for the proxy selected for this host, or None."""
    url = _select_proxy(host)
    if not url:
        return None
    parts = urlsplit(url)
    proxy = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
    if parts.username:
        proxy["username"] = parts.username
    if parts.password:
        proxy["password"] = parts.password
    return proxy


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
    context = _get_browser().new_context(
        storage_state=storage, user_agent=USER_AGENT, proxy=_pw_proxy(urlsplit(url).hostname)
    )
    try:
        if not ALLOW_PRIVATE:
            guarded_context(context)
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=timeout * 1000)
        if wait:
            page.wait_for_selector(wait, timeout=timeout * 1000)
        return page.content()
    finally:
        context.close()
