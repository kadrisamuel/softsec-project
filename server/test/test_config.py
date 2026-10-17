"""Checks for application runtime secrets"""

import pytest
from app import create_app
from app.config import _read_secret


def test_app_fails_when_secret_file_is_missing(monkeypatch, tmp_path):
    """A missing mounted secret must prevent startup."""

    monkeypatch.setenv("SECRET_KEY_FILE", str(tmp_path / "missing"))

    with pytest.raises(
        RuntimeError, match="Cannot read secret file from SECRET_KEY_FILE"
    ):
        _read_secret("SECRET_KEY_FILE")


def test_app_fails_when_secret_file_is_empty(monkeypatch, tmp_path):
    """An empty mounted secret must prevent startup."""

    secret_path = tmp_path / "empty"
    secret_path.write_text("", encoding="utf8")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_path))

    with pytest.raises(RuntimeError, match="Secret file from SECRET_KEY_FILE is empty"):
        _read_secret("SECRET_KEY_FILE")


def test_app_fails_when_secret_path_is_unset(monkeypatch):
    """Startup must not fall back to a fixed signing key."""

    monkeypatch.delenv("SECRET_KEY_FILE")

    with pytest.raises(
        RuntimeError, match="SECRET_KEY_FILE must point to a secret file"
    ):
        _read_secret("SECRET_KEY_FILE")


def test_app_correct_config(monkeypatch, tmp_path):  # mutmut identified
    """App configuration should be correct after successful init"""

    secret_path = tmp_path / "secret"
    secret_path.write_text("test-secret", encoding="utf8")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_path))

    salt_path = tmp_path / "salt"
    salt_path.write_text("test-salt", encoding="utf8")
    monkeypatch.setenv("SALT_FILE", str(salt_path))

    db_pass_path = tmp_path / "db_pass"
    db_pass_path.write_text("test-db-pass", encoding="utf8")
    monkeypatch.setenv("DB_PASS_FILE", str(db_pass_path))

    app = create_app()
    assert app.config["SECRET_KEY"] == "test-secret"
    assert app.config["SALT"] == "test-salt"
    assert app.config["DB_PASSWORD"] == "test-db-pass"
