import httpx
import pytest

import webfetch.client as fetchmod
from webfetch._safeurl import UnsafeURLError
from webfetch.client import download, fetch

HTML = (
    "<html><body>"
    + ("data point " * 80)
    + "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
    + "</body></html>"
)


def test_data_file_routes_to_pandas(monkeypatch):
    monkeypatch.setattr(
        fetchmod._http,
        "get",
        lambda url, timeout=30.0: httpx.Response(
            200, content=b"a,b\n1,2\n3,4\n", request=httpx.Request("GET", url)
        ),
    )
    r = fetch("http://x.test/data.csv")
    assert r.engine == "pandas"
    assert r.dataframe is not None
    assert list(r.dataframe.columns) == ["a", "b"]
    assert r.dataframe.shape == (2, 2)


def test_cache_hit_short_circuits(monkeypatch):
    monkeypatch.setattr(fetchmod.cache, "get", lambda url, scope=None: HTML.encode())

    def boom(*a, **k):
        raise AssertionError("network must not be touched on a cache hit")

    monkeypatch.setattr(fetchmod._http, "get", boom)
    r = fetch("http://x.test/page")
    assert r.from_cache is True
    assert r.engine == "cache"
    assert len(r.tables) == 1


def test_httpx_path_used_for_complete_pages(monkeypatch):
    monkeypatch.setattr(fetchmod.cache, "get", lambda url, scope=None: None)
    monkeypatch.setattr(fetchmod.cache, "put", lambda url, data, scope=None: None)
    monkeypatch.setattr(
        fetchmod._http, "get", lambda url, timeout=30.0: httpx.Response(200, text=HTML)
    )
    r = fetch("http://x.test/page")
    assert r.engine == "httpx"
    assert r.dataframe is not None


def test_escalates_to_browser_on_thin_response(monkeypatch):
    monkeypatch.setattr(fetchmod.cache, "get", lambda url, scope=None: None)
    monkeypatch.setattr(fetchmod.cache, "put", lambda url, data, scope=None: None)
    monkeypatch.setattr(
        fetchmod._http, "get", lambda url, timeout=30.0: httpx.Response(200, text="<html></html>")
    )
    monkeypatch.setattr(fetchmod, "ENGINE", "auto")
    monkeypatch.setattr(fetchmod._browser, "render", lambda url, wait, auth, timeout: HTML)
    r = fetch("http://x.test/spa")
    assert r.engine == "playwright"


def test_firecrawl_engine_path(monkeypatch):
    monkeypatch.setattr(fetchmod.cache, "get", lambda url, scope=None: None)
    monkeypatch.setattr(fetchmod.cache, "put", lambda url, data, scope=None: None)
    monkeypatch.setattr(
        fetchmod._http, "get", lambda url, timeout=30.0: httpx.Response(200, text="<html></html>")
    )
    monkeypatch.setattr(fetchmod, "ENGINE", "firecrawl")
    monkeypatch.setattr(fetchmod, "FIRECRAWL_API_KEY", "key")
    monkeypatch.setattr(fetchmod._firecrawl, "scrape", lambda url, timeout=30.0: ("# md", HTML))
    r = fetch("http://1.1.1.1/page")  # public IP literal so the target guard passes
    assert r.engine == "firecrawl"
    assert r.markdown == "# md"


def test_firecrawl_path_guards_target(monkeypatch):
    monkeypatch.setattr(fetchmod, "ENGINE", "firecrawl")
    monkeypatch.setattr(fetchmod, "FIRECRAWL_API_KEY", "key")
    monkeypatch.setattr(fetchmod.cache, "get", lambda url, scope=None: None)
    monkeypatch.setattr(fetchmod._firecrawl, "scrape", lambda url, timeout=30.0: ("x", "x"))
    # a private target must be blocked before it is handed to the managed API
    with pytest.raises(UnsafeURLError):
        fetch("http://127.0.0.1/x", render=True)


def test_download_writes_file(http_transport, tmp_path):
    http_transport(lambda request: httpx.Response(200, content=b"payload"))
    dest = tmp_path / "sub" / "out.bin"
    assert download("http://1.1.1.1/file", dest).read_bytes() == b"payload"


def test_download_enforces_max_bytes(http_transport, tmp_path):
    http_transport(lambda request: httpx.Response(200, content=b"0" * 5000))
    with pytest.raises(ValueError):
        download("http://1.1.1.1/big", tmp_path / "big.bin", max_bytes=1000)


def test_download_redirect_to_internal_blocked(http_transport, tmp_path):
    http_transport(
        lambda request: httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    with pytest.raises(UnsafeURLError):
        download("http://1.1.1.1/x", tmp_path / "x.bin")


def test_auth_fetch_is_never_cached(monkeypatch):
    puts = []
    monkeypatch.setattr(fetchmod.cache, "get", lambda url, scope=None: None)
    monkeypatch.setattr(fetchmod.cache, "put", lambda url, data: puts.append(url))
    monkeypatch.setattr(fetchmod._browser, "render", lambda url, wait, auth, timeout: HTML)
    r = fetch("http://x.test/private", auth=True)
    assert r.engine == "playwright"
    assert puts == []  # authenticated pages must not touch the disk cache
