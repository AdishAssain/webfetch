import pytest

from webfetch._browser import _allowed


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
def test_blocks_private_ranges_and_bad_schemes(url):
    assert _allowed(url) is False


@pytest.mark.parametrize("url", ["https://1.1.1.1/page", "http://8.8.8.8/x"])
def test_allows_public(url):
    assert _allowed(url) is True


def test_pw_proxy_parses_auth(monkeypatch):
    import webfetch._browser as b

    monkeypatch.setattr(b, "_select_proxy", lambda host=None: "http://user:pass@host:8080")
    assert b._pw_proxy() == {
        "server": "http://host:8080",
        "username": "user",
        "password": "pass",
    }


def test_pw_proxy_none_when_unset(monkeypatch):
    import webfetch._browser as b

    monkeypatch.setattr(b, "_select_proxy", lambda host=None: None)
    assert b._pw_proxy() is None


# ── non-network schemes must not be aborted ──────────────────────────────
#
# The route guard aborted every request whose scheme was not http(s). A login
# page is mostly not http(s): x.com drives its flow through blob: and data:
# URLs and about:blank iframes. Aborting those broke the page silently —
# clicking Continue did nothing — while protecting against nothing, because a
# data: or blob: URL makes no network request and so cannot reach a private
# host. file: still must be blocked: that one does read the local disk.


@pytest.mark.parametrize(
    "url",
    [
        "data:image/png;base64,iVBORw0KGgo=",
        "blob:https://x.com/6f1a-4c2e",
        "about:blank",
    ],
)
def test_route_allows_schemes_that_make_no_network_request(url):
    from webfetch._browser import _route_allowed

    assert _route_allowed(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "chrome-extension://abcdef/inject.js",
    ],
)
def test_route_still_blocks_local_and_unknown_schemes(url):
    """Fail closed: anything not known to be inert stays aborted."""
    from webfetch._browser import _route_allowed

    assert _route_allowed(url) is False


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/"])
def test_route_still_blocks_private_hosts(url):
    from webfetch._browser import _route_allowed

    assert _route_allowed(url) is False


def test_route_allows_public_http():
    from webfetch._browser import _route_allowed

    assert _route_allowed("https://1.1.1.1/page") is True
