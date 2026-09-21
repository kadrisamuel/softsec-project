import pytest

from app.config import Config


@pytest.fixture(autouse=True)
def enable_app_routes(monkeypatch):
    monkeypatch.setattr(Config, "ENABLE_MAIN_ROUTES", True)
    monkeypatch.setattr(Config, "ENABLE_AUTH_ROUTES", True)
    monkeypatch.setattr(Config, "ENABLE_DOCUMENT_ROUTES", True)
    monkeypatch.setattr(Config, "ENABLE_WATERMARKING_ROUTES", True)
