import json

import httpx
import pytest

from webfetch import client
from webfetch._safeurl import UnsafeURLError

URL = "https://1.1.1.1/supplement"
SNAPSHOT_URL = "https://web.archive.org/web/20260102030405/https://1.1.1.1/supplement"


def test_archive_fallback_is_opt_in_and_labels_snapshot(monkeypatch):
    from webfetch import _archive

    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return (
            client.Result(url=url, status=403, error="HTTP 403")
            if url == URL
            else client.Result(url=url, text="Archived supplement")
        )

    monkeypatch.setattr(client, "_fetch", fetch)
    monkeypatch.setattr(
        _archive, "wayback", lambda *a, **k: _archive.Snapshot(SNAPSHOT_URL, "20260102030405")
    )
    live = client.fetch(URL)
    assert live.status == 403
    assert calls == [URL]
    result = client.fetch(URL, archive=True)
    assert result.text == "Archived supplement"
    assert result.archive_url == SNAPSHOT_URL
    assert result.archive_timestamp == "20260102030405"
    assert "403" in result.fallback_reason
    assert calls == [URL, URL, SNAPSHOT_URL]


def test_archive_is_not_queried_after_live_success(monkeypatch):
    from webfetch import _archive

    monkeypatch.setattr(client, "_fetch", lambda *a, **k: client.Result(url=URL, text="live"))
    monkeypatch.setattr(_archive, "wayback", lambda *a, **k: pytest.fail("unnecessary lookup"))
    assert client.fetch(URL, archive=True).text == "live"


def test_archive_lookup_uses_guarded_http_and_upgrades_snapshot_https(monkeypatch):
    from webfetch import _archive

    seen = []

    def get(url, **kwargs):
        seen.append(url)
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "archived_snapshots": {
                    "closest": {
                        "available": True,
                        "status": "200",
                        "timestamp": "20260102030405",
                        "url": SNAPSHOT_URL.replace(
                            "https://web.archive.org", "http://web.archive.org"
                        ),
                    }
                }
            },
        )

    monkeypatch.setattr(_archive._http, "get", get)
    snapshot = _archive.wayback(URL)
    assert snapshot.url == SNAPSHOT_URL
    assert snapshot.timestamp == "20260102030405"
    assert seen == ["https://archive.org/wayback/available?url=https%3A%2F%2F1.1.1.1%2Fsupplement"]


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/", "http://169.254.169.254/", "file:///etc/passwd"]
)
def test_private_urls_are_not_disclosed_to_archive(monkeypatch, url):
    from webfetch import _archive

    monkeypatch.setattr(_archive._http, "get", lambda *a, **k: pytest.fail("private URL leaked"))
    with pytest.raises(UnsafeURLError):
        _archive.wayback(url)


def test_authenticated_fetch_cannot_fall_back_to_archive():
    with pytest.raises(ValueError, match="auth"):
        client.fetch(URL, auth=True, archive=True)


@pytest.mark.parametrize(
    "target",
    ["http://127.0.0.1/", "https://evil.test/fake", "https://web.archive.org.evil.test/web/x"],
)
def test_untrusted_snapshot_url_is_rejected(monkeypatch, target):
    from webfetch import _archive

    monkeypatch.setattr(
        _archive._http,
        "get",
        lambda url, **k: httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "archived_snapshots": {
                    "closest": {
                        "available": True,
                        "status": "200",
                        "url": target,
                        "timestamp": "20260102030405",
                    }
                }
            },
        ),
    )
    with pytest.raises(ValueError, match="snapshot"):
        _archive.wayback(URL)


def test_no_snapshot_preserves_original_failure(monkeypatch):
    from webfetch import _archive

    monkeypatch.setattr(
        client, "_fetch", lambda *a, **k: client.Result(url=URL, status=404, error="HTTP 404")
    )
    monkeypatch.setattr(_archive, "wayback", lambda *a, **k: None)
    result = client.fetch(URL, archive=True)
    assert result.status == 404
    assert not result.archive_url
    assert "no snapshot" in result.fallback_reason.lower()


def test_network_failure_can_use_archive(monkeypatch):
    from webfetch import _archive

    def fetch(url, **kwargs):
        if url == URL:
            raise httpx.ConnectError("offline")
        return client.Result(url=url, text="Archived supplement")

    monkeypatch.setattr(client, "_fetch", fetch)
    monkeypatch.setattr(
        _archive, "wayback", lambda *a, **k: _archive.Snapshot(SNAPSHOT_URL, "20260102030405")
    )
    assert client.fetch(URL, archive=True).archive_url == SNAPSHOT_URL


def test_cli_archive_flag_and_provenance(monkeypatch, capsys):
    from webfetch import __main__ as cli

    calls = []

    def fetch(url, **kwargs):
        calls.append(kwargs)
        return client.Result(
            url=SNAPSHOT_URL,
            text="Archived",
            archive_url=SNAPSHOT_URL,
            archive_timestamp="20260102030405",
        )

    monkeypatch.setattr(cli, "fetch", fetch)
    monkeypatch.setattr("sys.argv", ["webfetch", "get", URL, "--archive"])
    cli.main()
    assert calls[0]["archive"] is True
    output = capsys.readouterr()
    assert "20260102030405" in output.err
    assert SNAPSHOT_URL in output.err


def test_archive_api_redirect_to_metadata_is_blocked(http_transport, monkeypatch):
    from webfetch import _archive

    monkeypatch.setattr(
        "webfetch._safeurl._resolve",
        lambda host: [
            (None, None, None, None, (host if host == "169.254.169.254" else "1.1.1.1", 0))
        ],
    )
    http_transport(
        lambda request: httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    with pytest.raises(UnsafeURLError):
        _archive.wayback(URL)


@pytest.mark.parametrize(
    "closest", [{}, {"available": False}, {"available": True, "status": "404"}]
)
def test_unavailable_snapshot_returns_none(monkeypatch, closest):
    from webfetch import _archive

    monkeypatch.setattr(
        _archive._http,
        "get",
        lambda url, **k: httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"archived_snapshots": {"closest": closest}},
        ),
    )
    assert _archive.wayback(URL) is None


def test_broken_archive_preserves_live_error(monkeypatch):
    from webfetch import _archive

    def unavailable(*a, **k):
        raise httpx.ConnectError("archive unavailable")

    monkeypatch.setattr(
        client, "_fetch", lambda *a, **k: client.Result(url=URL, status=403, error="HTTP 403")
    )
    monkeypatch.setattr(_archive, "wayback", unavailable)
    result = client.fetch(URL, archive=True)
    assert result.status == 403
    assert "Wayback lookup/fetch failed" in result.fallback_reason


@pytest.mark.parametrize("section", ["payload", "archived_snapshots", "closest"])
@pytest.mark.parametrize("malformed", [None, [], "invalid", 17, False])
def test_malformed_archive_sections_preserve_live_failure(monkeypatch, section, malformed):
    from webfetch import _archive

    payload = malformed
    if section == "archived_snapshots":
        payload = {"archived_snapshots": malformed}
    elif section == "closest":
        payload = {"archived_snapshots": {"closest": malformed}}
    monkeypatch.setattr(
        _archive._http,
        "get",
        lambda url, **k: httpx.Response(
            200, request=httpx.Request("GET", url), content=json.dumps(payload)
        ),
    )
    assert _archive.wayback(URL) is None

    live = client.Result(url=URL, status=403, error="HTTP 403")
    monkeypatch.setattr(client, "_fetch", lambda *a, **k: live)
    result = client.fetch(URL, archive=True)
    assert result is live
    assert result.status == 403
    assert result.error == "HTTP 403"
    assert not result.archive_url
    assert "no snapshot" in result.fallback_reason.lower()


@pytest.mark.parametrize("malformed_url", [None, [], {}, 17, False, True])
def test_malformed_snapshot_urls_preserve_live_failure(monkeypatch, malformed_url):
    from webfetch import _archive

    monkeypatch.setattr(
        _archive._http,
        "get",
        lambda url, **k: httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "archived_snapshots": {
                    "closest": {
                        "available": True,
                        "status": "200",
                        "timestamp": "20260102030405",
                        "url": malformed_url,
                    }
                }
            },
        ),
    )
    assert _archive.wayback(URL) is None

    live = client.Result(url=URL, status=403, error="HTTP 403")
    monkeypatch.setattr(client, "_fetch", lambda *a, **k: live)
    result = client.fetch(URL, archive=True)
    assert result is live
    assert result.status == 403
    assert result.error == "HTTP 403"
    assert not result.archive_url
    assert "no snapshot" in result.fallback_reason.lower()
