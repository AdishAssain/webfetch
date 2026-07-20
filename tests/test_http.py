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
    http_transport(lambda request: httpx.Response(200, text="hello"))
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


def test_capped_stream_aborts_past_limit():
    class FakeStream:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        def read(self, max_bytes, timeout=None):
            return self._chunks.pop(0) if self._chunks else b""

    stream = _http._CappedStream(FakeStream([b"x" * 60, b"x" * 60]), limit=100)
    assert stream.read(1024) == b"x" * 60  # 60 <= 100 ok
    with pytest.raises(_http.ResponseTooLargeError):
        stream.read(1024)  # running total 120 > 100
