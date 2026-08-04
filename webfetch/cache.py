import hashlib
import json
import time
from pathlib import Path

from .config import CACHE_DIR, CACHE_TTL, ENGINE

SCHEMA = 2  # bump when the stored shape changes, so old entries expire on upgrade


def _path(url: str, scope: str | None = None) -> Path:
    """Cache path for a URL under a given fetch scope.

    The key carries the scope because the same URL does not return the same
    bytes under every one. A geo-aware proxy pool is the case that matters here:
    a page fetched through one exit IP was being served to a later request
    routed through another. Built from a canonical payload rather than string
    concatenation so the key stays stable as fields are added.
    """
    payload = json.dumps(
        {"url": url, "scope": scope or "", "engine": ENGINE, "schema": SCHEMA},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{digest}.html"


def get(url: str, ttl: int | None = None, scope: str | None = None) -> bytes | None:
    ttl = CACHE_TTL if ttl is None else ttl
    path = _path(url, scope)
    if not path.exists():
        return None
    if ttl and time.time() - path.stat().st_mtime > ttl:
        return None
    return path.read_bytes()


def put(url: str, data: bytes, scope: str | None = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(url, scope).write_bytes(data)
