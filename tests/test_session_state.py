"""Session-state validity, and what an aborted login must not do.

Both bugs here were found the same way. `webfetch login` was run from a shell
with no TTY, so the "press Enter" prompt raised EOFError immediately. It left a
0-byte storage_state.json behind, and `webfetch doctor` then reported
session-state as ok — a check passing on a file that cannot authenticate
anything.
"""

from __future__ import annotations

import json
import os

import pytest

from webfetch import auth, config, doctor

VALID_STATE = {
    "cookies": [{"name": "auth_token", "value": "x", "domain": ".x.com", "path": "/"}],
    "origins": [],
}


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    p = tmp_path / "storage_state.json"
    monkeypatch.setattr(config, "STATE_PATH", p)
    return p


def write(p, payload, mode=0o600):
    p.write_text(payload)
    p.chmod(mode)
    return p


class TestSessionStateCheck:
    def test_absent_file_warns(self, state_path):
        status, detail = doctor._session_state()
        assert status == doctor.WARN
        assert "no saved session" in detail

    def test_a_valid_session_passes(self, state_path):
        write(state_path, json.dumps(VALID_STATE))
        status, _ = doctor._session_state()
        assert status == doctor.OK

    def test_an_empty_file_does_not_pass(self, state_path):
        """The 0-byte file an aborted login leaves behind. Presence is not a session."""
        write(state_path, "")
        status, detail = doctor._session_state()
        assert status != doctor.OK
        assert "empty" in detail.lower()

    def test_unparseable_content_does_not_pass(self, state_path):
        write(state_path, "{truncated")
        status, detail = doctor._session_state()
        assert status != doctor.OK
        assert "unreadable" in detail.lower() or "parse" in detail.lower()

    def test_valid_json_with_no_cookies_or_origins_does_not_pass(self, state_path):
        """Playwright writes this shape when nothing was ever logged in."""
        write(state_path, json.dumps({"cookies": [], "origins": []}))
        status, detail = doctor._session_state()
        assert status != doctor.OK
        assert "empty" in detail.lower() or "no cookies" in detail.lower()

    def test_a_session_kept_only_in_local_storage_passes(self, state_path):
        """Some sites authenticate from localStorage rather than cookies."""
        write(
            state_path,
            json.dumps(
                {"cookies": [], "origins": [{"origin": "https://x.com", "localStorage": [{}]}]}
            ),
        )
        status, _ = doctor._session_state()
        assert status == doctor.OK

    def test_wrong_mode_still_fails(self, state_path):
        """The existing permission check must survive the new validity check."""
        write(state_path, json.dumps(VALID_STATE), mode=0o644)
        status, detail = doctor._session_state()
        assert status == doctor.FAIL
        assert "mode" in detail


class FakeContext:
    """Stands in for a Playwright context, capturing where it was asked to write."""

    def __init__(self, fail=False):
        self.fail = fail
        self.written_to = None

    def storage_state(self, path):
        if self.fail:
            raise RuntimeError("capture failed")
        self.written_to = path
        with open(path, "w") as fh:
            json.dump(VALID_STATE, fh)


class TestSaveState:
    def test_a_captured_session_is_written_with_owner_only_mode(self, tmp_path):
        target = tmp_path / "storage_state.json"
        auth._save_state(FakeContext(), target)
        assert json.loads(target.read_text()) == VALID_STATE
        assert target.stat().st_mode & 0o777 == 0o600

    def test_a_failed_capture_leaves_no_file_behind(self, tmp_path):
        """The 0-byte file must never appear."""
        target = tmp_path / "storage_state.json"
        with pytest.raises(RuntimeError):
            auth._save_state(FakeContext(fail=True), target)
        assert not target.exists()

    def test_a_failed_capture_does_not_destroy_an_existing_session(self, tmp_path):
        """Worse than the empty file: login pre-truncated the real one.

        Re-running login and aborting it wiped a session that was working.
        """
        target = tmp_path / "storage_state.json"
        write(target, json.dumps(VALID_STATE))
        with pytest.raises(RuntimeError):
            auth._save_state(FakeContext(fail=True), target)
        assert json.loads(target.read_text()) == VALID_STATE

    def test_no_temporary_file_is_left_in_the_directory(self, tmp_path):
        target = tmp_path / "storage_state.json"
        with pytest.raises(RuntimeError):
            auth._save_state(FakeContext(fail=True), target)
        assert os.listdir(tmp_path) == []

    def test_the_directory_is_owner_only(self, tmp_path):
        target = tmp_path / "nested" / "storage_state.json"
        auth._save_state(FakeContext(), target)
        assert target.parent.stat().st_mode & 0o777 == 0o700
