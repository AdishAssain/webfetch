from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from ._browser import _pw_proxy, guarded_context
from ._safeurl import guard
from .config import ALLOW_PRIVATE, STATE_PATH, USER_AGENT


def login(url: str, state_path: Path | str = STATE_PATH) -> Path:
    """Open a real browser, let you log in by hand, and save the session.

    Run this once per gated site (e.g. Nikshay). Afterwards fetch(url, auth=True)
    reuses the saved session. Credentials never touch code or the agent loop.
    """
    from playwright.sync_api import sync_playwright

    guard(url, allow_private=ALLOW_PRIVATE)
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.chmod(0o700)
    # Create the file 0600 before Playwright writes into it. Chmod-after-write
    # leaves the cookies world-readable for the duration of the write; a write
    # to an existing file preserves its mode, so pre-creating closes that window.
    fd = os.open(state_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=USER_AGENT, proxy=_pw_proxy(urlsplit(url).hostname)
        )
        if not ALLOW_PRIVATE:
            guarded_context(context)  # same per-request guard as render()
        context.new_page().goto(url)
        input("Log in in the opened window, then press Enter here to save the session… ")
        context.storage_state(path=str(state_path))
        state_path.chmod(0o600)  # session cookies — restrict to owner
        browser.close()
    return state_path
