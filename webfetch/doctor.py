"""Health check. Reports what works, what does not, and why.

Two audiences: a human running `webfetch doctor` after something broke, and a
caller like the dotclaude improver that shells out and needs a machine-readable
answer.

Offline checks run by default. --live adds one request per engine, which is the
only way to tell a configuration problem from a network one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _probe(name: str, fn, fix: str = "") -> Check:
    """Run one check, turning an unexpected exception into a FAIL with its type."""
    try:
        status, detail = fn()
    except Exception as exc:  # a check must never take the doctor down
        return Check(name, FAIL, f"{type(exc).__name__}: {exc}"[:200], fix)
    return Check(name, status, detail, fix if status != OK else "")


# ── offline checks ───────────────────────────────────────────────────────


def _playwright() -> tuple[str, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return FAIL, "playwright not importable"
    with sync_playwright() as p:
        path = Path(p.chromium.executable_path)
    if not path.exists():
        return FAIL, f"chromium missing at {path}"
    return OK, "chromium present"


def _yt_dlp() -> tuple[str, str]:
    if not shutil.which("yt-dlp"):
        return WARN, "not installed — the youtube adapter returns 501"
    out = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=30)
    return OK, out.stdout.strip() or "present"


def _cache_dir() -> tuple[str, str]:
    d = config.CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    probe = d / ".doctor-write-test"
    probe.write_text("x")
    probe.unlink()
    n = sum(1 for _ in d.glob("*.html"))
    return OK, f"{d} writable, {n} cached pages, ttl {config.CACHE_TTL}s"


def _session_state() -> tuple[str, str]:
    p = config.STATE_PATH
    if not p.exists():
        return WARN, f"no saved session at {p} — auth fetches and x.com return 401"
    mode = p.stat().st_mode & 0o777
    if mode != 0o600:
        return FAIL, f"{p} mode is {mode:o}, expected 600 — session cookies are readable"
    return OK, f"{p} present, mode 600"


def _search_provider() -> tuple[str, str]:
    if config.EXA_API_KEY:
        return OK, "exa key configured"
    if config.TAVILY_API_KEY:
        return OK, "tavily key configured"
    return WARN, "no EXA or TAVILY key — discover() raises"


def _ssrf_guard() -> tuple[str, str]:
    """The guard must reject non-public targets. Uses literals, so no DNS."""
    from ._safeurl import UnsafeURLError, _is_nonpublic
    from ._safeurl import ipaddress as ip

    must_block = ["127.0.0.1", "169.254.169.254", "10.0.0.1", "100.64.0.1", "::1"]
    leaked = [a for a in must_block if not _is_nonpublic(ip.ip_address(a))]
    if leaked:
        return FAIL, f"guard allows {', '.join(leaked)}"
    if _is_nonpublic(ip.ip_address("8.8.8.8")):
        return FAIL, "guard rejects public addresses — everything will fail"
    if config.ALLOW_PRIVATE:
        return WARN, "WEBFETCH_ALLOW_PRIVATE is set — the SSRF guard is disabled"
    _ = UnsafeURLError
    return OK, "blocks loopback, metadata, RFC1918, CGNAT, v6 loopback"


def _guarded_transport() -> tuple[str, str]:
    """Fails closed on an httpx/httpcore version it cannot patch, so check it."""
    from ._http import _guarded_transport as build

    build(None)
    return OK, "installs against the current httpx"


def _proxy_config() -> tuple[str, str]:
    if not config.PROXY and not config.PROXIES:
        return OK, "no proxy configured"
    count = len(config.PROXIES) or 1
    scope = ", ".join(config.PROXY_HOSTS) if config.PROXY_HOSTS else "all hosts"
    return OK, f"{count} proxy target(s), scope: {scope}"


# ── live checks ──────────────────────────────────────────────────────────


def _live(url: str, expect_engine: str) -> tuple[str, str]:
    from .client import fetch

    r = fetch(url, refresh=True)
    if r.status >= 400 or not r.text.strip():
        return FAIL, f"{r.engine} returned status {r.status}, {len(r.text)} chars"
    note = (
        "" if r.engine == expect_engine else f" (routed via {r.engine}, expected {expect_engine})"
    )
    return OK, f"{len(r.text)} chars via {r.engine}{note}"


def run(live: bool = False) -> list[Check]:
    checks = [
        _probe("ssrf-guard", _ssrf_guard, "review webfetch/_safeurl.py"),
        _probe("guarded-transport", _guarded_transport, "pin httpx; see _http._guarded_transport"),
        _probe("playwright", _playwright, "uv run playwright install chromium"),
        _probe("yt-dlp", _yt_dlp, "brew install yt-dlp"),
        _probe("cache-dir", _cache_dir, "check WEBFETCH_CACHE_DIR permissions"),
        _probe("session-state", _session_state, "webfetch login <url>"),
        _probe("search-provider", _search_provider, "set EXA_API_KEY in .env"),
        _probe("proxy-config", _proxy_config),
    ]
    if live:
        checks += [
            _probe("live:httpx", lambda: _live("https://example.com", "httpx"), "check network"),
            _probe(
                "live:reddit",
                lambda: _live("https://www.reddit.com/r/ClaudeCode/top/?t=week", "reddit"),
                "reddit may be rate-limiting; .json is blocked, .rss is not",
            ),
            _probe(
                "live:youtube",
                lambda: _live("https://www.youtube.com/watch?v=AJpK3YTTKZ4", "youtube"),
                "yt-dlp may be rate-limited or out of date",
            ),
        ]
    return checks


def report(checks: list[Check], as_json: bool = False) -> int:
    """Print the report. Returns a shell exit code: non-zero if anything failed."""
    if as_json:
        worst = (
            FAIL
            if any(c.status == FAIL for c in checks)
            else (WARN if any(c.status == WARN for c in checks) else OK)
        )
        print(json.dumps({"status": worst, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        for c in checks:
            mark = {OK: "ok  ", WARN: "WARN", FAIL: "FAIL"}[c.status]
            print(f"{mark}  {c.name:20} {c.detail}")
            if c.fix:
                print(f"        {'':20} fix: {c.fix}")
        failed = sum(c.status == FAIL for c in checks)
        warned = sum(c.status == WARN for c in checks)
        print(f"\n{len(checks)} checks, {failed} failed, {warned} warnings")
    return 1 if any(c.status == FAIL for c in checks) else 0


def env_summary() -> dict:
    """Non-secret configuration, for a failure report. Never includes key values."""
    return {
        "engine": config.ENGINE,
        "allow_private": config.ALLOW_PRIVATE,
        "max_bytes": config.MAX_BYTES,
        "max_redirects": config.MAX_REDIRECTS,
        "cache_dir": str(config.CACHE_DIR),
        "proxy_configured": bool(config.PROXY or config.PROXIES),
        "search_provider": "exa"
        if config.EXA_API_KEY
        else "tavily"
        if config.TAVILY_API_KEY
        else None,
        "yt_dlp": bool(shutil.which("yt-dlp")),
        "python": os.sys.version.split()[0],
    }
