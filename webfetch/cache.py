import hashlib
import time
from pathlib import Path

from .config import CACHE_DIR, CACHE_TTL


def _path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{digest}.html"


def get(url: str, ttl: int | None = None) -> bytes | None:
    ttl = CACHE_TTL if ttl is None else ttl
    path = _path(url)
    if not path.exists():
        return None
    if ttl and time.time() - path.stat().st_mtime > ttl:
        return None
    return path.read_bytes()


def put(url: str, data: bytes) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(url).write_bytes(data)
