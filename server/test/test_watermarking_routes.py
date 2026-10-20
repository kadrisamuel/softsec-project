import hashlib
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.watermarking import utils as watermarking_utils


@pytest.fixture
def secret() -> str:
    return "f" * 32


@pytest.fixture
def key() -> str:
    return "test-key"


def test_watermarking_blueprint_is_registered():
    app = create_app()

    assert "watermarking" in app.blueprints


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("POST", "/api/create-watermark"),
        ("POST", "/api/create-watermark/<int:document_id>"),
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
        ("POST", "/api/read-watermark"),
        ("POST", "/api/read-watermark/1"),
    ],
)
def test_protected_watermarking_route_requires_token(method, path):
    response = create_app().test_client().open(path, method=method)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json == {
        "error": "Missing or invalid Authorization header"
    }


def test_get_watermarking_methods_returns_registry():
    response = create_app().test_client().get("/api/get-watermarking-methods")

    assert response.status_code == HTTPStatus.OK
    assert response.is_json
    assert response.json["count"] == len(response.json["methods"])


def test_plugin_loader_route_is_not_registered():
    app = create_app()
    available_routes = {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        for method in rule.methods
    }

    assert ("POST", "/api/load-plugin") not in available_routes


@pytest.mark.parametrize("id_source", ["url", "json"])
def test_create_watermark_saves_version(
    route_app,
    auth_headers,
    sample_pdf,
    tmp_path,
    monkeypatch,
    id_source,
    secret,
    key,
):
    source_path = tmp_path / "report.pdf"
    source_path.write_bytes(sample_pdf)

    watermarked_bytes = sample_pdf + b"\n% test-watermark\n"
    check_applicable = MagicMock(return_value=True)
    apply_watermark = MagicMock(return_value=watermarked_bytes)
    monkeypatch.setattr(
        watermarking_utils, "is_watermarking_applicable", check_applicable
    )
    monkeypatch.setattr(watermarking_utils, "apply_watermark", apply_watermark)

    engine = route_app.extensions["tatou-db"]
    select_connection = engine.connect.return_value.__enter__.return_value
    select_connection.execute.return_value.first.return_value = SimpleNamespace(
        id=3, name="report.pdf", path="report.pdf"
    )
    insert_connection = engine.begin.return_value.__enter__.return_value
    version_id_result = MagicMock()
    version_id_result.scalar.return_value = 42
    insert_connection.execute.side_effect = [MagicMock(), version_id_result]

    payload = {
        "method": "rgb-dft-qim-v1",
        "intended_for": "Bob Smith",
        "secret": secret,
        "key": key,
    }
    path = "/api/create-watermark/3"
    if id_source == "json":
        path = "/api/create-watermark"
        payload["id"] = "3"

    response = route_app.test_client().post(
        path, json=payload, headers=auth_headers
    )

    filename = "report__Bob_Smith.pdf"
    link = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    destination = tmp_path / "watermarks" / filename
    assert response.status_code == HTTPStatus.CREATED
    assert response.json == {
        "id": 42,
        "documentid": 3,
        "link": link,
        "intended_for": "Bob Smith",
        "method": "rgb-dft-qim-v1",
        "position": None,
        "filename": filename,
        "size": len(watermarked_bytes),
    }
    assert destination.read_bytes() == watermarked_bytes
    check_applicable.assert_called_once_with(
        method="rgb-dft-qim-v1", pdf=str(source_path), position=None
    )
    apply_watermark.assert_called_once_with(
        pdf=str(source_path),
        secret=secret,
        key=key,
        method="rgb-dft-qim-v1",
        position=None,
    )
    select_statement, select_parameters = select_connection.execute.call_args.args
    assert "id = :id AND ownerid = :uid" in str(select_statement)
    assert select_parameters == {"id": 3, "uid": 7}
    assert insert_connection.execute.call_count == 2
    insert_statement, insert_parameters = (
        insert_connection.execute.call_args_list[0].args
    )
    assert "INSERT INTO Versions" in str(insert_statement)
    assert insert_parameters == {
        "documentid": 3,
        "link": link,
        "intended_for": "Bob Smith",
        "secret": secret,
        "method": "rgb-dft-qim-v1",
        "position": "",
        "path": destination,
    }
    assert str(insert_connection.execute.call_args_list[1].args[0]) == (
        "SELECT LAST_INSERT_ID()"
    )


@pytest.mark.parametrize(
    ("path", "use_relative_path"),
    [
        ("/api/read-watermark/3", True),
        ("/api/read-watermark", False),
    ],
)
def test_read_watermark_returns_extracted_secret(
    route_app,
    auth_headers,
    sample_pdf,
    tmp_path,
    monkeypatch,
    path,
    use_relative_path,
    secret,
    key,
):
    file_path = tmp_path / "document.pdf"
    file_path.write_bytes(sample_pdf)

    engine = route_app.extensions["tatou-db"]
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.first.return_value = SimpleNamespace(
        id=3,
        name="document.pdf",
        path=file_path.name if use_relative_path else str(file_path),
    )
    read_watermark = MagicMock(return_value=secret)
    monkeypatch.setattr(watermarking_utils, "read_watermark", read_watermark)

    payload = {"method": "rgb-dft-qim-v1", "key": key}
    if path == "/api/read-watermark":
        payload["id"] = "3"

    response = route_app.test_client().post(
        path, json=payload, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json == {
        "documentid": 3,
        "secret": secret,
        "method": "rgb-dft-qim-v1",
        "position": None,
    }
    read_watermark.assert_called_once_with(
        method="rgb-dft-qim-v1", pdf=str(file_path.resolve()), key=key
    )
    connection.execute.assert_called_once()
    statement, parameters = connection.execute.call_args.args
    assert "id = :id AND ownerid = :uid" in str(statement)
    assert parameters == {"id": 3, "uid": 7}


# TODO: Test that create-watermark returns 400 for an unknown method.
# TODO: Test read-watermark known client errors (400) and
# unexpected processing errors (500).
# TODO: Test that watermark database and missing-backing-file failures return 500.
