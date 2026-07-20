from __future__ import annotations

from pathlib import Path

from .config import STATE_PATH, USER_AGENT


def login(url: str, state_path: Path | str = STATE_PATH) -> Path:
    """Open a real browser, let you log in by hand, and save the session.

    Run this once per gated site (e.g. Nikshay). Afterwards fetch(url, auth=True)
    reuses the saved session. Credentials never touch code or the agent loop.
    """
    from playwright.sync_api import sync_playwright

    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent=USER_AGENT)
        context.new_page().goto(url)
        input("Log in in the opened window, then press Enter here to save the session… ")
        context.storage_state(path=str(state_path))
        state_path.chmod(0o600)  # session cookies — restrict to owner
        browser.close()
    return state_path
