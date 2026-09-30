"""Checks for required runtime secrets."""

import pytest

from app import create_app


def test_app_fails_when_secret_file_is_missing(monkeypatch, tmp_path):
    """A missing mounted secret must prevent startup."""

    monkeypatch.setenv("SECRET_KEY_FILE", str(tmp_path / "missing"))

    with pytest.raises(RuntimeError, match="Cannot read secret file from SECRET_KEY_FILE"):
        create_app()


def test_app_fails_when_secret_file_is_empty(monkeypatch, tmp_path):
    """An empty mounted secret must prevent startup."""

    secret_path = tmp_path / "empty"
    secret_path.write_text("", encoding="utf8")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_path))

    with pytest.raises(RuntimeError, match="Secret file from SECRET_KEY_FILE is empty"):
        create_app()


def test_app_fails_when_secret_path_is_unset(monkeypatch):
    """Startup must not fall back to a fixed signing key."""

    monkeypatch.delenv("SECRET_KEY_FILE")

    with pytest.raises(RuntimeError, match="SECRET_KEY_FILE must point to a secret file"):
        create_app()
