import pytest

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
