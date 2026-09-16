from unittest.mock import MagicMock

import pytest

from app import create_app
import app.main.routes as main_routes


def test_new_healthz():
    response = create_app().test_client().get("/healthz")

    assert response.status_code == 200
    assert response.is_json
    assert response.json["message"] == "The server is up and running."

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


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("GET", "/"),
        ("GET", "/<path:filename>"),
    ],
)
def test_static_route_is_registered(method, route):
    app = create_app()
    available_routes = {
        (available_method, rule.rule)
        for rule in app.url_map.iter_rules()
        for available_method in rule.methods
    }

    assert (method, route) in available_routes


@pytest.mark.parametrize("path", ["/", "/index.html", "/style.css"])
def test_static_file_is_served(path):
    response = create_app().test_client().get(path)

    assert response.status_code == 200
