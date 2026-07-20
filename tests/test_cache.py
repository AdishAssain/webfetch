import os
import time

import pytest

import webfetch.cache as cache


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "CACHE_TTL", 86400)


def test_put_get_roundtrip():
    cache.put("http://x/a", b"hello")
    assert cache.get("http://x/a") == b"hello"


def test_missing_returns_none():
    assert cache.get("http://x/missing") is None


def test_distinct_urls_get_distinct_entries():
    cache.put("http://x/a", b"A")
    cache.put("http://x/b", b"B")
    assert cache.get("http://x/a") == b"A"
    assert cache.get("http://x/b") == b"B"


def test_expired_entry_is_dropped():
    cache.put("http://x/a", b"hello")
    path = cache._path("http://x/a")
    old = time.time() - 100_000
    os.utime(path, (old, old))
    assert cache.get("http://x/a") is None
