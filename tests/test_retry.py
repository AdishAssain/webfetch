import httpx

import webfetch._http as _http


def test_get_retries_then_succeeds(http_transport, monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, text="ok")

    http_transport(handler)
    resp = _http.get("http://1.1.1.1/")
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_get_gives_up_after_max_retries(http_transport, monkeypatch):
    monkeypatch.setattr(_http.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(_http, "MAX_RETRIES", 2)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503)

    http_transport(handler)
    assert _http.get("http://1.1.1.1/").status_code == 503
    assert calls["n"] == 3  # initial + 2 retries


def test_retry_delay_honors_retry_after():
    resp = httpx.Response(503, headers={"retry-after": "2"})
    assert _http._retry_delay(resp, 0) == 2.0


def test_retry_delay_uses_jittered_exponential_backoff():
    # Full jitter: the delay is drawn from (0, ceiling], where the ceiling grows
    # exponentially. Callers that failed together must not retry together.
    resp = httpx.Response(503)
    ceiling = min(_http.RETRY_BACKOFF * 4, _http.MAX_RETRY_DELAY)
    draws = [_http._retry_delay(resp, 2) for _ in range(50)]
    assert all(0 <= d <= ceiling for d in draws)
    assert len(set(draws)) > 1, "delay is constant — jitter is not applied"


def test_retry_delay_ceiling_grows_with_attempt():
    resp = httpx.Response(503)
    early = max(_http._retry_delay(resp, 0) for _ in range(50))
    late = max(_http._retry_delay(resp, 3) for _ in range(50))
    assert late > early


def test_retry_delay_never_exceeds_the_cap():
    resp = httpx.Response(503)
    assert all(_http._retry_delay(resp, 20) <= _http.MAX_RETRY_DELAY for _ in range(50))


def test_throttle_sleeps_when_interval_set(monkeypatch):
    slept = []
    monkeypatch.setattr(_http, "MIN_INTERVAL", 1.0)
    monkeypatch.setattr(_http, "_last_seen", {})
    times = iter([100.0, 100.0, 100.2, 100.2])
    monkeypatch.setattr(_http.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(_http.time, "sleep", lambda s: slept.append(s))
    _http.throttle("host")  # first call: no prior timestamp -> no wait
    _http.throttle("host")  # 0.2s since last -> waits ~0.8s
    assert slept and round(slept[0], 1) == 0.8


def test_select_proxy_rotates(monkeypatch):
    monkeypatch.setattr(_http, "PROXIES", ["http://a", "http://b"])
    monkeypatch.setattr(_http, "_proxy_index", 0)
    assert [_http._select_proxy() for _ in range(3)] == ["http://a", "http://b", "http://a"]


def test_select_proxy_single(monkeypatch):
    monkeypatch.setattr(_http, "PROXIES", [])
    monkeypatch.setattr(_http, "PROXY", "http://p")
    assert _http._select_proxy() == "http://p"


def test_select_proxy_none(monkeypatch):
    monkeypatch.setattr(_http, "PROXIES", [])
    monkeypatch.setattr(_http, "PROXY", None)
    assert _http._select_proxy() is None


def test_proxy_only_for_matching_hosts(monkeypatch):
    monkeypatch.setattr(_http, "PROXY", "http://p")
    monkeypatch.setattr(_http, "PROXIES", [])
    monkeypatch.setattr(_http, "PROXY_HOSTS", ["gov.in"])
    assert _http._select_proxy("data.gov.in") == "http://p"  # subdomain
    assert _http._select_proxy("gov.in") == "http://p"  # exact
    assert _http._select_proxy("example.com") is None  # unmatched -> direct
    assert _http._select_proxy(None) is None


def test_host_matches_boundaries():
    assert _http._host_matches("data.gov.in", ["gov.in"]) is True
    assert _http._host_matches("gov.in", ["gov.in"]) is True
    assert _http._host_matches("evilgov.in", ["gov.in"]) is False  # not a suffix boundary
    assert _http._host_matches("GOV.IN", ["gov.in"]) is True  # case-insensitive
    assert _http._host_matches("data.gov.in.", ["gov.in"]) is True  # trailing dot
    assert _http._host_matches("data.gov.in", ["GOV.IN."]) is True  # suffix normalized too
    assert _http._host_matches(None, ["gov.in"]) is False
