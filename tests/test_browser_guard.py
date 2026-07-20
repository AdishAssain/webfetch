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
