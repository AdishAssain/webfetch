from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from . import _http
from ._safeurl import guard


@dataclass(frozen=True)
class Snapshot:
    url: str
    timestamp: str


def wayback(url: str, *, timeout: float = 30.0) -> Snapshot | None:
    """Look up an existing public Wayback snapshot; never create a capture."""
    guard(url, allow_private=False)
    if urlsplit(url).username is not None:
        raise ValueError("URLs with credentials cannot be sent to Wayback")
    response = _http.get(
        "https://archive.org/wayback/available?" + urlencode({"url": url}), timeout=timeout
    )
    response.raise_for_status()
    closest = response.json().get("archived_snapshots", {}).get("closest", {})
    if closest.get("available") is not True or str(closest.get("status")) != "200":
        return None
    timestamp = str(closest.get("timestamp", ""))
    target = urlsplit(closest.get("url", ""))
    if (
        target.scheme not in {"http", "https"}
        or target.netloc != "web.archive.org"
        or len(timestamp) != 14
        or not timestamp.isdecimal()
        or not target.path.startswith(f"/web/{timestamp}/")
    ):
        raise ValueError("Wayback returned an invalid snapshot URL or timestamp")
    return Snapshot(urlunsplit(target._replace(scheme="https")), timestamp)
