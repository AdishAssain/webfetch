"""Regressions for the findings confirmed by the 2026-07-31 security scan."""

import os
import stat
from types import SimpleNamespace

import httpx
import pytest

from webfetch import _browser
from webfetch._http import MAX_RETRY_DELAY, _retry_delay
from webfetch._safeurl import UnsafeURLError, _is_nonpublic, guard
from webfetch._safeurl import ipaddress as ip_mod


def _ip(addr):
    return ip_mod.ip_address(addr)


# ── ssrf.address-classification ──────────────────────────────────────────


@pytest.mark.parametrize(
    "addr",
    [
        "100.64.0.1",  # RFC 6598 shared address space — public per ipaddress
        "100.127.255.255",  # upper end of the same /10
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata
        "10.0.0.1",
        "192.168.1.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",  # v4-mapped loopback
    ],
)
def test_nonpublic_addresses_are_rejected(addr):
    assert _is_nonpublic(_ip(addr))


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700::1111", "100.63.255.255"])
def test_public_addresses_are_allowed(addr):
    # 100.63.255.255 sits just below the shared-address-space block and must
    # not be caught by it.
    assert not _is_nonpublic(_ip(addr))


def test_guard_rejects_shared_address_space(monkeypatch):
    monkeypatch.setattr(
        "webfetch._safeurl._resolve", lambda host: [(None, None, None, None, ("100.64.0.1", 0))]
    )
    with pytest.raises(UnsafeURLError, match="100.64.0.1"):
        guard("https://carrier.example.com")


# ── resource-exhaustion.retry-after ──────────────────────────────────────


def _resp(retry_after):
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(429, headers=headers)


def test_retry_after_is_clamped():
    # Unclamped this parked the caller for roughly 31 years.
    assert _retry_delay(_resp("999999999"), 0) == MAX_RETRY_DELAY


def test_retry_after_honoured_below_the_cap():
    assert _retry_delay(_resp("5"), 0) == 5.0


def test_negative_retry_after_falls_back_to_backoff():
    assert _retry_delay(_resp("-10"), 0) > 0


def test_unparsable_retry_after_falls_back_to_backoff():
    # HTTP-date form is not honoured; it must not raise or return zero.
    assert _retry_delay(_resp("Wed, 21 Oct 2026 07:28:00 GMT"), 1) > 0


def test_backoff_grows_without_the_header():
    assert _retry_delay(_resp(None), 2) > _retry_delay(_resp(None), 0)


# ── credential-exposure.session-file-permissions ─────────────────────────


def test_login_creates_session_file_unreadable_by_others(tmp_path, monkeypatch):
    state = tmp_path / "nested" / "state.json"

    def fake_sync_playwright():
        # The file must already be 0600 by the time Playwright would write it.
        assert state.exists(), "session file should be pre-created"
        assert stat.S_IMODE(state.stat().st_mode) == 0o600
        raise RuntimeError("stop before launching a browser")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", fake_sync_playwright)
    monkeypatch.setattr("webfetch.auth.guard", lambda url, allow_private=False: url)

    from webfetch.auth import login

    with pytest.raises(RuntimeError, match="stop before launching"):
        login("https://example.com", state_path=state)

    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.parent.stat().st_mode) == 0o700
    assert not os.access(state, os.X_OK)


# ── ssrf.browser-dns-rebinding ───────────────────────────────────────────


def test_resolver_rules_pin_the_validated_address(monkeypatch):
    monkeypatch.setattr(_browser, "ALLOW_PRIVATE", False)
    monkeypatch.setattr(
        "webfetch._browser.resolve_public", lambda host, allow_private: "93.184.216.34"
    )
    assert _browser._resolver_rules("https://example.com/x") == "MAP example.com 93.184.216.34"


def test_resolver_rules_propagate_a_blocked_address(monkeypatch):
    def blocked(host, allow_private):
        raise UnsafeURLError("blocked non-public address: 127.0.0.1")

    monkeypatch.setattr(_browser, "ALLOW_PRIVATE", False)
    monkeypatch.setattr("webfetch._browser.resolve_public", blocked)
    with pytest.raises(UnsafeURLError):
        _browser._resolver_rules("https://rebind.example.com")


def test_no_resolver_rules_when_private_is_allowed(monkeypatch):
    monkeypatch.setattr(_browser, "ALLOW_PRIVATE", True)
    assert _browser._resolver_rules("https://example.com") is None


def test_changing_host_relaunches_the_browser(monkeypatch):
    launched = []

    class FakeBrowser:
        def close(self):
            launched.append("closed")

    class FakeChromium:
        def launch(self, headless, args):
            launched.append(args)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            pass

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: SimpleNamespace(start=FakePlaywright)
    )
    monkeypatch.setattr(_browser, "_browser", None)
    monkeypatch.setattr(_browser, "_browser_rules", None)

    _browser._get_browser("MAP a.example 1.2.3.4")
    _browser._get_browser("MAP a.example 1.2.3.4")  # same rules — reused
    _browser._get_browser("MAP b.example 5.6.7.8")  # different — relaunch

    assert launched.count("closed") == 1
    assert [a for a in launched if a != "closed"] == [
        ["--host-resolver-rules=MAP a.example 1.2.3.4"],
        ["--host-resolver-rules=MAP b.example 5.6.7.8"],
    ]
    _browser._shutdown()
