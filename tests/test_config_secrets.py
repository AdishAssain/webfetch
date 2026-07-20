import subprocess

import webfetch.config as config


def test_plain_value_passthrough(monkeypatch):
    monkeypatch.setenv("WF_TEST_KEY", "raw-value")
    assert config._secret("WF_TEST_KEY") == "raw-value"


def test_missing_returns_none(monkeypatch):
    monkeypatch.delenv("WF_TEST_KEY", raising=False)
    assert config._secret("WF_TEST_KEY") is None


def test_op_reference_is_resolved(monkeypatch):
    monkeypatch.setenv("WF_TEST_KEY", "op://Vault/Item/field")

    class Done:
        stdout = "resolved-secret\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert config._secret("WF_TEST_KEY") == "resolved-secret"


def test_op_failure_falls_back_to_reference(monkeypatch):
    monkeypatch.setenv("WF_TEST_KEY", "op://Vault/Item/field")

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "op")

    monkeypatch.setattr(subprocess, "run", boom)
    assert config._secret("WF_TEST_KEY") == "op://Vault/Item/field"


def test_op_not_installed_falls_back(monkeypatch):
    monkeypatch.setenv("WF_TEST_KEY", "op://Vault/Item/field")

    def boom(*a, **k):
        raise OSError("op not found")

    monkeypatch.setattr(subprocess, "run", boom)
    assert config._secret("WF_TEST_KEY") == "op://Vault/Item/field"
