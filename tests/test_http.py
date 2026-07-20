import httpx
import pytest

import webfetch._http as _http
from webfetch._safeurl import UnsafeURLError


def test_redirect_to_internal_is_blocked(http_transport):
    def handler(request):
        if request.url.host == "1.1.1.1":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})
        return httpx.Response(200, text="should never reach here")

    http_transport(handler)
    with pytest.raises(UnsafeURLError):
        _http.get("http://1.1.1.1/")


def test_too_many_redirects(http_transport):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://1.1.1.1/next"})

    http_transport(handler)
    with pytest.raises(httpx.TooManyRedirects):
        _http.get("http://1.1.1.1/")


def test_normal_get(http_transport):
    def handler(request):
        return httpx.Response(200, text="hello")

    http_transport(handler)
    resp = _http.get("http://1.1.1.1/")
    assert resp.status_code == 200
    assert resp.text == "hello"


def test_follows_one_public_redirect(http_transport):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "http://1.1.1.1/end"})
        return httpx.Response(200, text="arrived")

    http_transport(handler)
    assert _http.get("http://1.1.1.1/start").text == "arrived"


def test_check_size_boundaries():
    _http.check_size(None)  # no header -> allowed
    _http.check_size(str(_http.MAX_BYTES))  # exactly at cap -> allowed
    with pytest.raises(ValueError):
        _http.check_size(str(_http.MAX_BYTES + 1))
