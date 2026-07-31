from __future__ import annotations

import atexit
from urllib.parse import urlsplit

from ._http import _select_proxy
from ._safeurl import UnsafeURLError, guard, resolve_public
from .config import ALLOW_PRIVATE, STATE_PATH, USER_AGENT

_playwright = None
_browser = None
_browser_rules: str | None = None
_atexit_registered = False


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


def _get_browser(resolver_rules: str | None = None):
    """Launch Chromium once and reuse it — launching is the expensive part.

    resolver_rules pins Chromium's own DNS. The guard and the browser otherwise
    resolve separately, so a hostname can answer the guard with a public address
    and Chromium with a loopback one. Reusing the browser only works while the
    rules are unchanged, so a different target host forces a relaunch; repeated
    fetches of the same host do not.
    """
    global _playwright, _browser, _browser_rules
    if _browser is not None and _browser_rules != resolver_rules:
        _shutdown()
    if _browser is None:
        from playwright.sync_api import sync_playwright

        args = [f"--host-resolver-rules={resolver_rules}"] if resolver_rules else []
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True, args=args)
        _browser_rules = resolver_rules
        _register_shutdown()
    return _browser


def _register_shutdown() -> None:
    """atexit registration, once per process rather than once per relaunch."""
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_shutdown)
        _atexit_registered = True


def _shutdown() -> None:
    global _playwright, _browser, _browser_rules
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None
    _browser_rules = None


def _resolver_rules(url: str) -> str | None:
    """Pin the target host to the address the guard validated.

    Closes the check/connect race for the navigation host. Subresources on other
    hosts are still checked per request by guarded_context() but are not pinned,
    so they keep the smaller version of the same race.
    """
    if ALLOW_PRIVATE:
        return None
    host = urlsplit(url).hostname
    if not host:
        return None
    return f"MAP {host} {resolve_public(host, allow_private=False)}"


def render(url: str, wait: str | None, auth: bool, timeout: float) -> str:
    guard(url, allow_private=ALLOW_PRIVATE)
    storage = str(STATE_PATH) if auth and STATE_PATH.exists() else None
    # A fresh context per fetch keeps cookies/auth isolated; the browser is reused.
    context = _get_browser(_resolver_rules(url)).new_context(
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
