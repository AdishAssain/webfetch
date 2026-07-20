import pytest

import webfetch.search as disc


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _capturing_post(store, payload):
    def post(url, **kwargs):
        store["url"] = url
        store["headers"] = kwargs.get("headers", {})
        store["json"] = kwargs.get("json", {})
        return _Resp(payload)

    return post


def test_no_key_raises(monkeypatch):
    monkeypatch.setattr(disc, "EXA_API_KEY", None)
    monkeypatch.setattr(disc, "TAVILY_API_KEY", None)
    with pytest.raises(RuntimeError):
        disc.discover("q")


def test_exa_payload_and_parsing(monkeypatch):
    store = {}
    payload = {
        "results": [
            {"url": "http://a", "title": "A", "highlights": ["h1", "h2"]},
            {"url": "http://b", "title": "B", "text": "body"},
        ]
    }
    monkeypatch.setattr(disc, "EXA_API_KEY", "exa-key")
    monkeypatch.setattr(disc, "TAVILY_API_KEY", None)
    monkeypatch.setattr(disc.httpx, "post", _capturing_post(store, payload))

    out = disc.discover("gpus", n=5, search_type="auto")

    assert out == [
        {"url": "http://a", "title": "A", "text": "h1\nh2"},
        {"url": "http://b", "title": "B", "text": "body"},
    ]
    assert store["url"] == "https://api.exa.ai/search"
    assert store["headers"]["x-api-key"] == "exa-key"
    body = store["json"]
    assert body["type"] == "auto"
    assert body["numResults"] == 5
    assert body["contents"] == {"highlights": True}
    for deprecated in (
        "useAutoprompt",
        "text",
        "summary",
        "highlights",
        "livecrawl",
        "numSentences",
    ):
        assert deprecated not in body


def test_exa_domain_filters(monkeypatch):
    store = {}
    monkeypatch.setattr(disc, "EXA_API_KEY", "k")
    monkeypatch.setattr(disc, "TAVILY_API_KEY", None)
    monkeypatch.setattr(disc.httpx, "post", _capturing_post(store, {"results": []}))
    disc.discover("q", include_domains=["who.int"], exclude_domains=["spam.com"])
    assert store["json"]["includeDomains"] == ["who.int"]
    assert store["json"]["excludeDomains"] == ["spam.com"]


def test_tavily_uses_bearer_header_not_body(monkeypatch):
    store = {}
    payload = {"results": [{"url": "u", "title": "t", "content": "c"}]}
    monkeypatch.setattr(disc, "EXA_API_KEY", None)
    monkeypatch.setattr(disc, "TAVILY_API_KEY", "tvly-secret")
    monkeypatch.setattr(disc.httpx, "post", _capturing_post(store, payload))

    out = disc.discover("q")

    assert out == [{"url": "u", "title": "t", "text": "c"}]
    assert store["headers"]["Authorization"] == "Bearer tvly-secret"
    # security: the key must never travel in the request body
    assert "api_key" not in store["json"]
    assert "tvly-secret" not in str(store["json"])


def test_tavily_domain_filters_are_forwarded(monkeypatch):
    store = {}
    monkeypatch.setattr(disc, "EXA_API_KEY", None)
    monkeypatch.setattr(disc, "TAVILY_API_KEY", "k")
    monkeypatch.setattr(disc.httpx, "post", _capturing_post(store, {"results": []}))
    disc.discover("q", include_domains=["who.int"], exclude_domains=["spam.com"])
    assert store["json"]["include_domains"] == ["who.int"]
    assert store["json"]["exclude_domains"] == ["spam.com"]
