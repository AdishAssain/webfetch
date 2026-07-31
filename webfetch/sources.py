"""Per-site adapters for sources the generic HTML path cannot reach.

Routed from `fetch()` before any other engine. Each adapter returns a Result or
None; None means "not my URL, carry on".

Why these three need special handling:
  youtube  the watch page carries no transcript — captions come from a separate
           endpoint that yt-dlp knows how to reach
  reddit   the .json endpoints are blocked by network security; .rss and
           old.reddit.com are not
  x        unauthenticated access returns 429, so the saved login session is the
           only route
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com", "np.reddit.com"}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}

YT_TIMEOUT = 120
# Prefer the original track: en-orig is the real transcript, en-<lang> are machine
# translations of it. Asking for several at once trips YouTube's rate limiter.
YT_SUB_LANGS = "en-orig,en,en-US,en-GB"


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def route(url: str, *, auth: bool = False):
    """Return a Result for a site needing special handling, else None."""
    host = host_of(url)
    if host in YOUTUBE_HOSTS:
        return youtube(url)
    if host in REDDIT_HOSTS:
        return reddit(url)
    if host in X_HOSTS:
        return x(url, auth=auth)
    return None


# ── YouTube ──────────────────────────────────────────────────────────────


def youtube(url: str):
    """Fetch title/channel/date plus the English transcript via yt-dlp.

    Nothing is downloaded but subtitles and metadata.
    """
    from .client import Result

    if not _have("yt-dlp"):
        return Result(url=url, status=501, text="yt-dlp not installed", engine="youtube")

    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--no-simulate",
                "--no-update",
                "--write-info-json",
                "--write-auto-sub",
                "--write-sub",
                "--sub-lang",
                YT_SUB_LANGS,
                "--sub-format",
                "vtt",
                "-o",
                f"{tmp}/%(id)s.%(ext)s",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=YT_TIMEOUT,
        )
        files = list(Path(tmp).iterdir())
        info = next((f for f in files if f.name.endswith(".info.json")), None)
        meta = json.loads(info.read_text()) if info else {}

        # en-orig is the real transcript; the others are translations of it.
        subs = sorted(
            (f for f in files if f.suffix == ".vtt"),
            key=lambda f: (0 if "orig" in f.name else 1, len(f.name)),
        )
        transcript = _vtt_to_text(subs[0].read_text()) if subs else ""

    if not transcript and not meta:
        return Result(
            url=url,
            status=502,
            text=f"yt-dlp failed: {proc.stderr.strip()[-300:]}",
            engine="youtube",
        )

    header = "\n".join(
        f"{k}: {v}"
        for k, v in (
            ("title", meta.get("title")),
            ("channel", meta.get("channel") or meta.get("uploader")),
            ("published", meta.get("upload_date")),
            ("duration_s", meta.get("duration")),
        )
        if v
    )
    body = f"{header}\n\n{transcript}".strip()
    return Result(
        url=url,
        status=200 if transcript else 204,
        text=body,
        markdown=body,
        engine="youtube",
    )


def _vtt_to_text(vtt: str) -> str:
    """Flatten a WebVTT caption file to prose.

    Auto-captions repeat each line as the next cue scrolls in, so consecutive
    duplicates are dropped — otherwise a transcript triples in size.
    """
    out: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
            or "-->" in line
            or line.isdigit()
        ):
            continue
        line = re.sub(r"<[^>]+>", "", line)  # inline timing and <c> tags
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out)


# ── Reddit ───────────────────────────────────────────────────────────────


def reddit(url: str):
    """Reddit via .rss for listings and old.reddit.com for posts.

    The .json API is blocked outright; both of these return 200 to plain httpx.
    """
    from . import _extract, _http
    from .client import Result

    parsed = urlparse(url)

    if "/comments/" in parsed.path:
        # Single post: old.reddit renders comments server-side.
        target, is_feed = url.replace(parsed.netloc, "old.reddit.com", 1), False
    else:
        # Listing: .rss carries title, author, link and body per entry.
        base = url.split("?")[0].rstrip("/")
        target = base if base.endswith(".rss") else f"{base}/.rss"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        is_feed = True

    resp = _http.get(target, timeout=30.0)
    if resp.status_code >= 400:
        return Result(url=target, status=resp.status_code, text="", engine="reddit")

    text = _feed_to_text(resp.text) if is_feed else _extract.clean_text(resp.text)
    return Result(
        url=target,
        status=resp.status_code,
        html=resp.text,
        text=text,
        markdown=text,
        engine="reddit",
    )


def _feed_to_text(xml: str) -> str:
    """Atom feed to one block per entry: title, author, link, body."""
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    blocks = []
    for entry in entries:
        title = _tag(entry, "title")
        author = _tag(entry, "name")
        updated = _tag(entry, "updated")
        link = re.search(r'<link[^>]*href="([^"]+)"', entry)
        body = _unescape(re.sub(r"<[^>]+>", " ", _tag(entry, "content")))
        blocks.append(
            "\n".join(
                filter(
                    None,
                    [
                        f"## {title}" if title else "",
                        f"by {author} · {updated}" if author else "",
                        link.group(1) if link else "",
                        re.sub(r"\s+", " ", body).strip()[:4000],
                    ],
                )
            )
        )
    return "\n\n".join(blocks)


def _tag(xml: str, name: str) -> str:
    match = re.search(rf"<{name}[^>]*>(.*?)</{name}>", xml, re.S)
    return _unescape(match.group(1)).strip() if match else ""


def _unescape(text: str) -> str:
    for entity, char in (
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&#32;", " "),
        ("&nbsp;", " "),
        ("&amp;", "&"),
    ):
        text = text.replace(entity, char)
    return text


# ── x.com ────────────────────────────────────────────────────────────────


def x(url: str, *, auth: bool = False):
    """x.com through the saved login session.

    Unauthenticated requests get 429 from every public endpoint, including the
    syndication one. Run `webfetch login https://x.com` once to save a session.
    """
    from . import _browser, _extract
    from .client import Result
    from .config import STATE_PATH

    if not Path(STATE_PATH).exists():
        return Result(
            url=url,
            status=401,
            text="x.com needs a saved session — run: webfetch login https://x.com",
            engine="x",
        )

    html = _browser.render(url, wait="article", auth=True, timeout=45.0)
    text = _extract.clean_text(html)
    return Result(url=url, status=200, html=html, text=text, markdown=text, engine="x")


def _have(binary: str) -> bool:
    from shutil import which

    return which(binary) is not None
