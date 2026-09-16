import pytest

from app import create_app


def test_watermarking_blueprint_is_registered():
    app = create_app()

    assert "watermarking" in app.blueprints


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("POST", "/api/create-watermark"),
        ("POST", "/api/create-watermark/<int:document_id>"),
        ("POST", "/api/load-plugin"),
        ("GET", "/api/get-watermarking-methods"),
        ("POST", "/api/read-watermark"),
        ("POST", "/api/read-watermark/<int:document_id>"),
    ],
)
def test_watermarking_route_is_registered(method, route):
    app = create_app()
    available_routes = {
        (available_method, rule.rule)
        for rule in app.url_map.iter_rules()
        for available_method in rule.methods
    }

    assert (method, route) in available_routes


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/create-watermark"),
        ("POST", "/api/create-watermark/1"),
        ("POST", "/api/load-plugin"),
        ("POST", "/api/read-watermark"),
        ("POST", "/api/read-watermark/1"),
    ],
)
def test_protected_watermarking_route_requires_token(method, path):
    response = create_app().test_client().open(path, method=method)

    assert response.status_code == 401
    assert response.json == {
        "error": "Missing or invalid Authorization header"
    }


def test_get_watermarking_methods_returns_registry():
    response = create_app().test_client().get("/api/get-watermarking-methods")

    assert response.status_code == 200
    assert response.is_json
    assert response.json["count"] == len(response.json["methods"])
