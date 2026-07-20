from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from . import _browser, _extract, _firecrawl, _http, cache
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


def fetch(
    url: str,
    *,
    render: bool = False,
    auth: bool = False,
    wait: str | None = None,
    refresh: bool = False,
    timeout: float = 30.0,
) -> Result:
    """Fetch a URL, auto-routing: data file -> pandas; cache -> httpx -> browser.

    render/auth force the browser path; auth also loads the saved login session.
    """
    if _ext(url) in DATA_EXT:
        return _data(url)

    heavy = render or auth
    if not heavy and not refresh:
        hit = cache.get(url)
        if hit is not None:
            return _from_html(
                url, hit.decode("utf-8", "replace"), 200, engine="cache", from_cache=True
            )

    if not heavy:
        resp = _http.get(url, timeout=timeout)
        if resp.status_code < 400 and _looks_complete(resp.text):
            cache.put(url, resp.text.encode("utf-8"))
            return _from_html(url, resp.text, resp.status_code, engine="httpx")

    if ENGINE == "firecrawl" and FIRECRAWL_API_KEY and not auth:
        guard(url, allow_private=ALLOW_PRIVATE)  # gate the target even via the managed API
        markdown, html = _firecrawl.scrape(url, timeout=timeout)
        cache.put(url, html.encode("utf-8"))
        result = _from_html(url, html, 200, engine="firecrawl")
        result.markdown = markdown or result.markdown
        return result

    html = _browser.render(url, wait=wait, auth=auth, timeout=timeout)
    if not auth:
        cache.put(url, html.encode("utf-8"))
    return _from_html(url, html, 200, engine="playwright")


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
                resp.raise_for_status()
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
