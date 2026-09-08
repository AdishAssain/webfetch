from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

from . import _archive, _browser, _extract, _firecrawl, _http, cache, sources
from ._safeurl import guard
from .config import ALLOW_PRIVATE, ENGINE, FIRECRAWL_API_KEY, MAX_BYTES, MIN_TEXT_CHARS

DATA_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".json"}


@dataclass
class Result:
    url: str
    status: int = 200
    html: str = ""
    text: str = ""
    markdown: str = ""
    tables: list[pd.DataFrame] = field(default_factory=list)
    dataframe: pd.DataFrame | None = None
    from_cache: bool = False
    engine: str = "httpx"
    # Diagnostics. A successful retry and a silent engine fallback both look
    # like a clean fetch from the outside; these are how a caller sees them.
    attempts: int = 1
    fallback_reason: str = ""
    error: str = ""
    archive_url: str = ""
    archive_timestamp: str = ""


def fetch(
    url: str,
    *,
    render: bool = False,
    auth: bool = False,
    wait: str | None = None,
    refresh: bool = False,
    timeout: float = 30.0,
    archive: bool = False,
) -> Result:
    """Fetch a URL, auto-routing: data file -> pandas; cache -> httpx -> browser.

    render/auth/wait force the browser path; auth also loads the saved login session.
    archive opts into an existing Wayback snapshot if a public live fetch fails.
    """
    kwargs = dict(render=render, auth=auth, wait=wait, refresh=refresh, timeout=timeout)
    if not archive:
        return _fetch(url, **kwargs)
    if auth:
        raise ValueError("Wayback fallback cannot be used with auth=True")
    guard(url, allow_private=False)
    if urlparse(url).username is not None:
        raise ValueError("URLs with credentials cannot be sent to Wayback")

    from playwright.sync_api import Error as BrowserError

    result = None
    original_error = None
    try:
        result = _fetch(url, **kwargs)
    except (httpx.HTTPError, BrowserError) as exc:
        original_error = exc
    if result is not None and not result.error and result.status < 400:
        return result

    reason = (
        f"live {result.engine} status {result.status}: {result.error}"
        if result is not None
        else f"live fetch failed: {type(original_error).__name__}"
    )
    try:
        snapshot = _archive.wayback(url, timeout=timeout)
        if snapshot is not None:
            archived = _fetch(snapshot.url, refresh=refresh, timeout=timeout)
            if not archived.error and archived.status < 400:
                archived.archive_url = snapshot.url
                archived.archive_timestamp = snapshot.timestamp
                archived.fallback_reason = "; ".join(
                    filter(None, [reason, archived.fallback_reason])
                )
                return archived
            reason += f"; Wayback snapshot failed: HTTP {archived.status}: {archived.error}"
        else:
            reason += "; Wayback: no snapshot available"
    except (httpx.HTTPError, BrowserError, ValueError) as exc:
        reason += f"; Wayback lookup/fetch failed: {type(exc).__name__}"
    if original_error is not None:
        raise original_error
    result.fallback_reason = "; ".join(filter(None, [result.fallback_reason, reason]))
    return result


def _fetch(
    url: str,
    *,
    render: bool = False,
    auth: bool = False,
    wait: str | None = None,
    refresh: bool = False,
    timeout: float = 30.0,
) -> Result:
    if _ext(url) in DATA_EXT:
        return _data(url)

    # Sites the generic HTML path cannot reach (youtube, reddit, x) route first.
    special = sources.route(url, auth=auth)
    if special is not None:
        return special

    heavy = render or auth or wait is not None
    # The exit IP changes what a geo-aware site returns, so it is part of the
    # cache key rather than an invisible dimension.
    scope = _http._select_proxy(urlparse(url).hostname)
    if not heavy and not refresh:
        hit = cache.get(url, scope=scope)
        if hit is not None:
            result = _from_html(
                url, hit.decode("utf-8", "replace"), 200, engine="cache", from_cache=True
            )
            if not result.error:
                return result

    fallback_reason = ""
    if not heavy:
        resp = _http.get(url, timeout=timeout)
        if resp.status_code < 400 and _looks_complete(resp.text):
            if resp.status_code == 200:
                cache.put(url, resp.text.encode("utf-8"), scope=scope)
            result = _from_html(url, resp.text, resp.status_code, engine="httpx")
            result.attempts = getattr(resp, "_webfetch_attempts", 1)
            return result
        # Escalating to a browser is a fallback, not a success. Record why, or
        # a site that quietly stopped serving usable HTML looks the same as one
        # that always needed rendering.
        fallback_reason = f"httpx status {resp.status_code}"
        if resp.status_code < 400:
            fallback_reason += (
                f"; body below MIN_TEXT_CHARS ({len(_extract.clean_text(resp.text))} chars)"
            )

    if ENGINE == "firecrawl" and FIRECRAWL_API_KEY and not auth and wait is None:
        guard(url, allow_private=ALLOW_PRIVATE)  # gate the target even via the managed API
        markdown, html = _firecrawl.scrape(url, timeout=timeout)
        result = _from_html(url, html, 200, engine="firecrawl")
        result.markdown = markdown or result.markdown
        if result.markdown.strip():
            result.error = ""
        if not result.error and result.text.strip():
            cache.put(url, html.encode("utf-8"), scope=scope)
        result.fallback_reason = fallback_reason
        return result

    page = _browser.render_page(url, wait=wait, auth=auth, timeout=timeout)
    result = _from_html(page.url, page.html, page.status, engine="playwright")
    # An authenticated render is never cached: the bytes are scoped to a session
    # the key does not carry.
    if not auth and not result.error and result.status == 200:
        cache.put(url, page.html.encode("utf-8"), scope=scope)
    result.fallback_reason = fallback_reason
    return result


def read_tables(url: str, **kwargs) -> list[pd.DataFrame]:
    return fetch(url, **kwargs).tables


def download(
    url: str, dest: str | Path, *, timeout: float = 60.0, max_bytes: int = MAX_BYTES
) -> Path:
    """Stream a URL to disk (SSRF-guarded) with a size cap, per-host throttling,
    and retry+backoff on 429/5xx.

    Writes to a temp file and renames on success, so a failed or oversized
    download never leaves a truncated file at dest.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    host = urlparse(url).hostname
    try:
        for attempt in range(_http.MAX_RETRIES + 1):
            _http.throttle(host)
            with _http.client(timeout, host=host) as http, http.stream("GET", url) as resp:
                if resp.status_code in _http.RETRY_STATUS and attempt < _http.MAX_RETRIES:
                    _http.backoff(resp, attempt)
                    continue
                if resp.status_code in {401, 403}:
                    reason = (
                        "Cloudflare challenge"
                        if resp.headers.get("cf-mitigated") == "challenge"
                        else "upstream access denied (cause not established)"
                    )
                    raise httpx.HTTPStatusError(
                        f"download: HTTP {resp.status_code}: {reason}. "
                        "download() is HTTP-only; it does not render challenges or reuse "
                        "browser login sessions.",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"download: HTTP {resp.status_code}; "
                        "expected a complete HTTP 200 response. "
                        "No file was saved.",
                        request=resp.request,
                        response=resp,
                    )
                total = 0
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError(f"download exceeds {max_bytes} bytes")
                        fh.write(chunk)
            tmp.replace(dest)
            return dest
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _ext(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def _looks_complete(html: str) -> bool:
    return len(_extract.clean_text(html)) > MIN_TEXT_CHARS


def _from_html(url, html, status, *, engine, from_cache=False) -> Result:
    text = _extract.clean_text(html)
    tabs = _extract.tables(html)
    error = ""
    if status >= 400:
        error = f"{engine} returned HTTP {status}"
    elif not text.strip() and not tabs:
        error = (
            "Empty content after extraction; the page may require a browser wait, "
            "login, or challenge completion."
        )
    return Result(
        url=url,
        status=status,
        html=html,
        text=text,
        markdown=text,
        tables=tabs,
        dataframe=tabs[0] if tabs else None,
        from_cache=from_cache,
        engine=engine,
        error=error,
    )


def _data(url: str) -> Result:
    resp = _http.get(url)
    resp.raise_for_status()
    buf = io.BytesIO(resp.content)
    readers = {
        ".csv": pd.read_csv,
        ".tsv": lambda b: pd.read_csv(b, sep="\t"),
        ".xlsx": pd.read_excel,
        ".xls": pd.read_excel,
        ".parquet": pd.read_parquet,
        ".json": pd.read_json,
    }
    df = readers[_ext(url)](buf)
    return Result(url=url, dataframe=df, tables=[df], engine="pandas")
