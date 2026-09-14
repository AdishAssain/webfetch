"""Tests for the pre-commit guard that keeps private detail out of a public repo.

Written after the repo was pushed to while being believed private. The checks
that mattered were all judgement calls made by a human or an assistant, and one
of them was wrong. These are deterministic instead: a pattern either matches or
it does not, and the hook fails the commit either way.

Every check below is exercised in both directions. A guard that has never been
made to fail is not evidence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "guard_public.py"


def run_guard(*paths):
    """Run the guard over `paths`; returns (exit_code, combined output)."""
    proc = subprocess.run(
        [sys.executable, str(GUARD), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def write(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


class TestSecrets:
    @pytest.mark.parametrize(
        "body",
        [
            "EXA_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456",
            "token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'",
            "aws = AKIAIOSFODNN7EXAMPLE",
            "slack = xoxb-1234567890-abcdefghijkl",
            # Assembled rather than written out: the repo's detect-private-key
            # hook scans this file too, and it does not honour the guard's
            # exemption list. The file written to disk still holds the full
            # marker, so the guard is exercised exactly as it would be in anger.
            "-----" + "BEGIN RSA " + "PRIVATE KEY-----",
        ],
    )
    def test_secret_shaped_values_fail(self, tmp_path, body):
        code, out = run_guard(write(tmp_path, "config.py", body))
        assert code != 0
        assert "secret" in out.lower()

    def test_an_empty_placeholder_passes(self, tmp_path):
        """.env.example must stay committable."""
        code, out = run_guard(write(tmp_path, ".env.example", "EXA_API_KEY=\n# TAVILY_API_KEY=\n"))
        assert code == 0, out

    def test_an_op_reference_passes(self, tmp_path):
        """A 1Password reference is a pointer, not a secret."""
        code, out = run_guard(
            write(tmp_path, ".env.example", "EXA_API_KEY=op://Private/Exa/credential\n")
        )
        assert code == 0, out


class TestCredentialFiles:
    @pytest.mark.parametrize(
        "name", [".env", "storage_state.json", "server.pem", "credentials.json"]
    )
    def test_credential_filenames_fail(self, tmp_path, name):
        code, out = run_guard(write(tmp_path, name, "anything"))
        assert code != 0
        assert "never be committed" in out.lower() or "credential" in out.lower()

    def test_env_example_is_allowed(self, tmp_path):
        code, out = run_guard(write(tmp_path, ".env.example", "KEY=\n"))
        assert code == 0, out


class TestPrivateReferences:
    @pytest.mark.parametrize(
        "body",
        [
            "webfetch login https://reports.nikshay.in",
            "contact adish@artpark.in for access",
            "WEBFETCH_PROXY_HOSTS=data.gov.in,nikshay.in",
        ],
    )
    def test_internal_references_fail(self, tmp_path, body):
        code, out = run_guard(write(tmp_path, "README.md", body))
        assert code != 0
        assert "internal" in out.lower() or "private reference" in out.lower()

    def test_example_hosts_pass(self, tmp_path):
        code, out = run_guard(
            write(tmp_path, "README.md", "webfetch login https://portal.example.com")
        )
        assert code == 0, out


class TestHomePaths:
    def test_an_absolute_home_path_fails(self, tmp_path):
        """A home path leaks the account name into a public repo."""
        code, out = run_guard(
            write(tmp_path, "notes.md", "run /Users/someperson/Developer/thing.py")
        )
        assert code != 0
        assert "home path" in out.lower()

    def test_a_tilde_path_passes(self, tmp_path):
        code, out = run_guard(write(tmp_path, "notes.md", "run ~/Developer/thing.py"))
        assert code == 0, out

    def test_the_guard_does_not_flag_itself(self):
        """The guard holds the very patterns it searches for."""
        code, out = run_guard(GUARD)
        assert code == 0, out


class TestClean:
    def test_a_clean_file_passes(self, tmp_path):
        code, out = run_guard(write(tmp_path, "mod.py", "def f():\n    return 1\n"))
        assert code == 0, out

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        """pre-commit can pass a path deleted in the same commit."""
        code, _ = run_guard(tmp_path / "gone.py")
        assert code == 0


class TestAuthorEmail:
    """The work address in this repo's history cannot be reliably removed from a
    public repo, so the control has to prevent the next one rather than undo it.

    The blocked domain lives in the guard, not in the hook config: the config is
    scanned, and a literal domain there trips the guard's own internal-ref rule.
    """

    def run_author(self, email):
        proc = subprocess.run(
            [sys.executable, str(GUARD), "--check-author"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "GIT_AUTHOR_EMAIL_OVERRIDE": email},
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_a_work_address_is_refused(self):
        code, out = self.run_author("someone@artpark.in")
        assert code != 0
        assert "work address" in out.lower()

    def test_a_personal_address_passes(self):
        code, out = self.run_author("someone@gmail.com")
        assert code == 0, out

    def test_a_github_noreply_address_passes(self):
        code, out = self.run_author("123+user@users.noreply.github.com")
        assert code == 0, out
