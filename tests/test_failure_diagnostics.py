from types import SimpleNamespace

import httpx
import pytest

from webfetch import _browser, client, search

URL = "https://1.1.1.1/supplement"
HTML = "<html><body>" + "Supplement data " * 50 + "</body></html>"


@pytest.fixture
def fetch_env(monkeypatch):
    writes = []
    monkeypatch.setattr(client, "ENGINE", "auto")
    monkeypatch.setattr(client.cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(client.cache, "put", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(client._http, "get", lambda *a, **k: httpx.Response(202, text=""))
    return writes


def test_browser_status_is_preserved(monkeypatch, fetch_env):
    page = SimpleNamespace(html=HTML, status=403, url=URL)
    monkeypatch.setattr(_browser, "render_page", lambda *a, **k: page, raising=False)
    monkeypatch.setattr(_browser, "render", lambda *a, **k: HTML)
    result = client.fetch(URL)
    assert result.status == 403
    assert result.error
    assert fetch_env == []


def test_empty_supplement_is_diagnosed_and_not_cached(monkeypatch, fetch_env):
    html = '<html><body>\n<script src="https://token.awswaf.com/challenge.js"></script>\n</body></html>'
    page = SimpleNamespace(html=html, status=202, url=URL)
    monkeypatch.setattr(_browser, "render_page", lambda *a, **k: page, raising=False)
    monkeypatch.setattr(_browser, "render", lambda *a, **k: html)
    result = client.fetch(URL)
    assert result.status == 202
    assert "empty" in result.error.lower()
    assert "httpx status 202" in result.fallback_reason
    assert fetch_env == []


def test_empty_cache_does_not_prevent_recovery(monkeypatch, fetch_env):
    monkeypatch.setattr(client.cache, "get", lambda *a, **k: b"<html><body>\n</body></html>")
    monkeypatch.setattr(client._http, "get", lambda *a, **k: httpx.Response(200, text=HTML))
    result = client.fetch(URL)
    assert result.engine == "httpx"
    assert "Supplement data" in result.text


def test_empty_firecrawl_result_is_not_cached(monkeypatch, fetch_env):
    monkeypatch.setattr(client, "ENGINE", "firecrawl")
    monkeypatch.setattr(client, "FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(client._firecrawl, "scrape", lambda *a, **k: ("", "<html></html>"))
    result = client.fetch(URL)
    assert result.error
    assert fetch_env == []


def test_wait_forces_render_even_with_complete_cache(monkeypatch, fetch_env):
    calls = []
    monkeypatch.setattr(client.cache, "get", lambda *a, **k: HTML.encode())

    def render(*a, **kwargs):
        calls.append(kwargs["wait"])
        return SimpleNamespace(html=HTML, status=200, url=URL)

    monkeypatch.setattr(_browser, "render_page", render, raising=False)
    client.fetch(URL, wait="a.download")
    assert calls == ["a.download"]


@pytest.mark.parametrize("key", [None, "", "op://Private/Exa/credential"])
def test_bad_search_configuration_never_reaches_provider(monkeypatch, key):
    calls = []
    monkeypatch.setattr(search, "EXA_API_KEY", key)
    monkeypatch.setattr(search, "_resolve_secret", lambda value: value, raising=False)
    monkeypatch.setattr(search.httpx, "post", lambda *a, **k: calls.append(k))
    with pytest.raises(RuntimeError, match="EXA_API_KEY"):
        search.discover("q", provider="exa")
    assert calls == []


def test_exa_recovers_when_1password_becomes_available_after_import(monkeypatch):
    sent = []
    monkeypatch.setattr(search, "EXA_API_KEY", "op://Private/Exa/credential")
    monkeypatch.setattr(search, "_resolve_secret", lambda value: "resolved-key", raising=False)

    def post(url, **kwargs):
        sent.append(kwargs["headers"]["x-api-key"])
        return httpx.Response(200, request=httpx.Request("POST", url), json={"results": []})

    monkeypatch.setattr(search.httpx, "post", post)
    assert search.discover("q", provider="exa") == []
    assert sent == ["resolved-key"]


def test_doctor_does_not_call_unresolved_exa_key_healthy(monkeypatch):
    from webfetch import doctor

    monkeypatch.setattr(doctor.config, "EXA_API_KEY", "op://Private/Exa/credential")
    monkeypatch.setattr(doctor.config, "TAVILY_API_KEY", None)
    status, detail = doctor._search_provider()
    assert status == doctor.FAIL
    assert "1Password" in detail
    assert "op://" not in detail


def test_doctor_live_search_checks_actual_authentication(monkeypatch):
    from webfetch import doctor

    def unauthorized(*a, **k):
        response = httpx.Response(401, request=httpx.Request("POST", "https://api.exa.ai/search"))
        raise httpx.HTTPStatusError(
            "check EXA_API_KEY: HTTP 401", request=response.request, response=response
        )

    monkeypatch.setattr(search, "discover", unauthorized)
    check = doctor._probe("live:search", doctor._live_search)
    assert check.status == doctor.FAIL
    assert "401" in check.detail


@pytest.mark.parametrize("provider,status", [("exa", 401), ("tavily", 403)])
def test_search_auth_error_is_actionable_without_echoing_secrets(monkeypatch, provider, status):
    key = "secret-that-must-not-be-printed"
    monkeypatch.setattr(search, "EXA_API_KEY", key)
    monkeypatch.setattr(search, "TAVILY_API_KEY", key)
    response = httpx.Response(status, text=key, request=httpx.Request("POST", "https://1.1.1.1"))
    monkeypatch.setattr(search.httpx, "post", lambda *a, **k: response)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        search.discover("q", provider=provider)
    assert f"{provider.upper()}_API_KEY" in str(caught.value)
    assert key not in str(caught.value)
    assert caught.value.response.status_code == status


def test_cloudflare_download_failure_identifies_http_only_path(http_transport, tmp_path):
    http_transport(lambda request: httpx.Response(403, headers={"cf-mitigated": "challenge"}))
    dest = tmp_path / "paper.pdf"
    dest.write_bytes(b"existing file")
    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.download(URL, dest)
    message = str(caught.value)
    assert "Cloudflare" in message
    assert "HTTP-only" in message
    assert caught.value.response.status_code == 403
    assert dest.read_bytes() == b"existing file"
    assert not dest.with_suffix(".pdf.part").exists()


@pytest.mark.parametrize("status", [202, 204, 206])
def test_download_rejects_incomplete_responses(http_transport, tmp_path, status):
    http_transport(lambda request: httpx.Response(status, content=b""))
    dest = tmp_path / "paper.pdf"
    dest.write_bytes(b"existing file")
    with pytest.raises(httpx.HTTPStatusError, match=str(status)):
        client.download(URL, dest)
    assert dest.read_bytes() == b"existing file"
    assert not dest.with_suffix(".pdf.part").exists()


def test_browser_metadata_and_context_cleanup(monkeypatch):
    closed = []
    page = SimpleNamespace(
        goto=lambda *a, **k: SimpleNamespace(status=202),
        content=lambda: "<html></html>",
        url=URL,
        on=lambda *a: None,
        wait_for_function=lambda *a, **k: None,
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: closed.append(True))
    browser = SimpleNamespace(new_context=lambda **k: context)
    monkeypatch.setattr(_browser, "_get_browser", lambda *a: browser)
    monkeypatch.setattr(_browser, "guarded_context", lambda *a: None)
    monkeypatch.setattr(_browser, "_pw_proxy", lambda *a: None)
    render_page = getattr(_browser, "render_page", _browser.render)
    result = render_page(URL, wait=None, auth=False, timeout=10)
    assert result.status == 202
    assert result.url == URL
    assert result.html == "<html></html>"
    assert closed == [True]


def test_http_non_200_is_not_cached_as_200(monkeypatch, fetch_env):
    monkeypatch.setattr(client._http, "get", lambda *a, **k: httpx.Response(202, text=HTML))
    result = client.fetch(URL)
    assert result.status == 202
    assert fetch_env == []


@pytest.mark.parametrize("wait", [None, "a[href]"])
def test_browser_wait_observes_final_document_status(monkeypatch, wait):
    callbacks = {}

    class Page:
        main_frame = object()
        url = URL
        html = "<html><body><script>load()</script></body></html>"

        def on(self, event, callback):
            callbacks[event] = callback

        def goto(self, *a, **k):
            return SimpleNamespace(status=202)

        def content(self):
            return self.html

        def finish(self, *a, **k):
            self.html = "<html><body>The page cannot be found</body></html>"
            callbacks["response"](
                SimpleNamespace(
                    status=404,
                    frame=self.main_frame,
                    request=SimpleNamespace(is_navigation_request=lambda: True),
                )
            )
            callbacks["response"](
                SimpleNamespace(
                    status=200,
                    frame=self.main_frame,
                    request=SimpleNamespace(is_navigation_request=lambda: False),
                )
            )

        wait_for_selector = finish
        wait_for_function = finish

    page = Page()
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    monkeypatch.setattr(
        _browser, "_get_browser", lambda *a: SimpleNamespace(new_context=lambda **k: context)
    )
    monkeypatch.setattr(_browser, "guarded_context", lambda *a: None)
    monkeypatch.setattr(_browser, "_pw_proxy", lambda *a: None)
    result = _browser.render_page(URL, wait=wait, auth=False, timeout=10)
    assert result.status == 404
    assert "cannot be found" in result.html


@pytest.mark.parametrize("status,error", [(202, "Empty content after extraction"), (403, "Denied")])
def test_cli_failed_fetch_is_visible_and_nonzero(monkeypatch, capsys, status, error):
    from webfetch import __main__ as cli

    result = client.Result(url=URL, status=status, error=error, fallback_reason="httpx status 202")
    monkeypatch.setattr(cli, "fetch", lambda *a, **k: result)
    monkeypatch.setattr("sys.argv", ["webfetch", "get", URL])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    output = capsys.readouterr()
    assert error in output.err
    assert result.fallback_reason in output.err


def test_cli_forwards_wait_and_refresh(monkeypatch):
    from webfetch import __main__ as cli

    calls = []

    def fetch(*a, **kwargs):
        calls.append(kwargs)
        return client.Result(url=URL, text="Supplement")

    monkeypatch.setattr(cli, "fetch", fetch)
    monkeypatch.setattr("sys.argv", ["webfetch", "get", URL, "--wait", "a.download", "--refresh"])
    cli.main()
    assert calls[0]["wait"] == "a.download"
    assert calls[0]["refresh"] is True


def test_markdown_only_firecrawl_success_is_not_lost_in_html_cache(monkeypatch, fetch_env):
    monkeypatch.setattr(client, "ENGINE", "firecrawl")
    monkeypatch.setattr(client, "FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(client._firecrawl, "scrape", lambda *a, **k: ("# Supplement", ""))
    result = client.fetch(URL)
    assert result.markdown == "# Supplement"
    assert not result.error
    assert fetch_env == []
