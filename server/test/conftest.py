from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.auth.tokens import create_token
from app.config import Config


@pytest.fixture(autouse=True)
def enable_app_routes(monkeypatch, tmp_path):
    for env_name in ("SECRET_KEY_FILE", "SALT_FILE", "DB_PASS_FILE"):
        secret_path = tmp_path / env_name.lower()
        secret_path.write_text(f"test-{env_name}", encoding="utf8")
        monkeypatch.setenv(env_name, str(secret_path))

    monkeypatch.setattr(Config, "ENABLE_MAIN_ROUTES", True)
    monkeypatch.setattr(Config, "ENABLE_AUTH_ROUTES", True)
    monkeypatch.setattr(Config, "ENABLE_DOCUMENT_ROUTES", True)
    monkeypatch.setattr(Config, "ENABLE_WATERMARKING_ROUTES", True)


@pytest.fixture
def sample_pdf() -> bytes:
    return (Path(__file__).parent / "samples" / "sample_1.pdf").read_bytes()


@pytest.fixture
def route_app(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, STORAGE_DIR=tmp_path)
    app.extensions["tatou-db"] = MagicMock()
    return app


@pytest.fixture
def auth_headers(route_app):
    with route_app.app_context():
        token = create_token(7, "alice", "user@example.com")
    return {"Authorization": f"Bearer {token}"}
