from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from ._browser import _pw_proxy, guarded_context
from ._safeurl import guard
from .config import ALLOW_PRIVATE, STATE_PATH, USER_AGENT


def _save_state(context, state_path: Path | str) -> Path:
    """Write a captured session to `state_path`, atomically and owner-only.

    Playwright is pointed at a temporary file in the same directory, which is
    renamed over the target only once the capture has succeeded. Two failures
    this prevents, both seen in practice after `webfetch login` was run without
    a TTY and its prompt raised EOFError:

      - a 0-byte storage_state.json left behind, which `doctor` then reported
        as a healthy session
      - the previous, working session destroyed, because the old code opened
        the real path O_TRUNC before the prompt, so aborting truncated it

    The temporary file is created 0600 by mkstemp, which keeps the property the
    pre-creation was there for: cookies are never briefly world-readable.
    """
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.chmod(0o700)

    fd, tmp = tempfile.mkstemp(dir=state_path.parent, prefix=".storage_state.", suffix=".tmp")
    os.close(fd)
    try:
        context.storage_state(path=tmp)
        os.chmod(tmp, 0o600)  # session cookies — restrict to owner
        os.replace(tmp, state_path)
    except BaseException:
        # Includes KeyboardInterrupt and EOFError, which is how this went wrong.
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return state_path


def login(url: str, state_path: Path | str = STATE_PATH) -> Path:
    """Open a real browser, let you log in by hand, and save the session.

    Run this once per gated site (e.g. Nikshay). Afterwards fetch(url, auth=True)
    reuses the saved session. Credentials never touch code or the agent loop.

    Needs a terminal: the confirmation prompt reads stdin. Run from a shell with
    a TTY, not from a non-interactive one, where it raises EOFError at once.
    """
    from playwright.sync_api import sync_playwright

    guard(url, allow_private=ALLOW_PRIVATE)
    state_path = Path(state_path)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context(
                user_agent=USER_AGENT, proxy=_pw_proxy(urlsplit(url).hostname)
            )
            if not ALLOW_PRIVATE:
                guarded_context(context)  # same per-request guard as render()
            context.new_page().goto(url)
            input("Log in in the opened window, then press Enter here to save the session… ")
            _save_state(context, state_path)
        finally:
            browser.close()
    return state_path
