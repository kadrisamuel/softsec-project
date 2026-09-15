from unittest.mock import MagicMock

from app import create_app
from server import app as old_app
import app.main.routes as main_routes


def check_healthz(app):
    response = app.test_client().get("/healthz")

    assert response.status_code == 200
    assert response.is_json
    assert response.json["message"] == "The server is up and running."

# Remove after migration done
def test_old_healthz():
    check_healthz(old_app)


def test_new_healthz():
    check_healthz(create_app())

# Tests route behavior only
def test_healthz_database_connected(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr(main_routes, "get_engine", lambda: engine)

    response = create_app().test_client().get("/healthz")

    assert response.status_code == 200
    assert response.json["db_connected"] is True
    engine.connect.return_value.__enter__.return_value.execute.assert_called_once()

# Tests route behavior only
def test_healthz_database_disconnected(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(main_routes, "get_engine", lambda: engine)

    response = create_app().test_client().get("/healthz")

    assert response.status_code == 200
    assert response.json["db_connected"] is False