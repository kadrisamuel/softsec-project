import datetime as dt
import hashlib
import io
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.documents.routes
import pytest
from app import create_app
from app.auth.tokens import create_token
from sqlalchemy import create_engine, text


@pytest.fixture
def storage_root() -> Path:
    return Path("/storage")


def test_sha256_file():  # mutmut identified
    checksum = app.documents.routes._sha256_file(Path("test/samples/sample_1.pdf"))  # pylint: disable=protected-access

    assert (
        checksum == "67ab12b4f39058f2b18daedc00137409107e8f4da7802e8e66ea58d6c22b4b31"
    )


@pytest.mark.parametrize(
    "test_path",
    ["sub/file", "./sub/file"],
)
def test_safe_resolve_under_storage_relative(
    test_path, storage_root: Path
):  # mutmut identified
    path = app.documents.routes._safe_resolve_under_storage(  # pylint: disable=protected-access
        Path(test_path), storage_root
    )

    assert path == storage_root / test_path


def test_safe_resolve_under_storage_absolute(storage_root: Path):  # mutmut identified
    test_path = storage_root / "sub/file"
    path = app.documents.routes._safe_resolve_under_storage(test_path, storage_root)  # pylint: disable=protected-access

    assert path == test_path


@pytest.mark.parametrize(
    "test_path",
    [
        "../file",
        "/file",
    ],
)
def test_safe_resolve_under_storage_escape(
    test_path, storage_root: Path
):  # mutmut identified
    with pytest.raises(RuntimeError):
        app.documents.routes._safe_resolve_under_storage(Path(test_path), storage_root)  # pylint: disable=protected-access


def test_documents_blueprint_is_registered():
    app = create_app()

    assert "documents" in app.blueprints


def test_list_documents_preserves_missing_token_response():
    response = create_app().test_client().get("/api/list-documents")

    assert response.status_code == 401
    assert response.json == {"error": "Missing or invalid Authorization header"}


def test_list_documents_returns_documents():
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.connect.return_value.__enter__.return_value
    query_result = MagicMock()
    query_result.all.return_value = [
        SimpleNamespace(
            id=3,
            name="report.pdf",
            creation=dt.datetime(2026, 9, 16, 10, 30),
            sha256_hex="ABC123",
            size=2048,
        )
    ]
    connection.execute.return_value = query_result

    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    response = app.test_client().get(
        "/api/list-documents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json == {
        "documents": [
            {
                "id": 3,
                "name": "report.pdf",
                "creation": "2026-09-16T10:30:00",
                "sha256": "ABC123",
                "size": 2048,
            }
        ]
    }
    assert connection.execute.call_args.args[1] == {"uid": 7}


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("GET", "/api/list-versions"),
        ("GET", "/api/list-versions/<int:document_id>"),
        ("GET", "/api/list-all-versions"),
        ("GET", "/api/get-document"),
        ("GET", "/api/get-document/<int:document_id>"),
        ("GET", "/api/get-version/<link>"),
    ],
)
def test_read_only_document_route_is_registered(method, route):
    app = create_app()
    available_routes = {
        (available_method, rule.rule)
        for rule in app.url_map.iter_rules()
        for available_method in rule.methods or ()
    }

    assert (method, route) in available_routes


@pytest.mark.parametrize(
    "path",
    [
        "/api/list-versions",
        "/api/list-versions/1",
        "/api/list-all-versions",
        "/api/get-document",
        "/api/get-document/1",
    ],
)
def test_read_only_document_route_requires_token(path):
    response = create_app().test_client().get(path)

    assert response.status_code == 401
    assert response.json == {"error": "Missing or invalid Authorization header"}


@pytest.mark.parametrize(
    ("path", "name", "download_name"),
    [
        ("/api/get-document/3", "report.pdf", "report.pdf"),
        ("/api/get-document?id=3", "report", "report.pdf"),
        ("/api/get-document?documentid=3", "report.PDF", "report.PDF"),
    ],
)
def test_get_document_returns_owned_pdf(
    route_app, auth_headers, sample_pdf, tmp_path, path, name, download_name
):
    file_path = tmp_path / "stored.pdf"
    file_path.write_bytes(sample_pdf)
    checksum = hashlib.sha256(sample_pdf).hexdigest()

    engine = route_app.extensions["tatou-db"]
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.first.return_value = SimpleNamespace(
        id=3,
        name=name,
        path=str(file_path),
        sha256_hex=checksum.upper(),
        size=len(sample_pdf),
    )

    with route_app.test_client().get(path, headers=auth_headers) as response:
        assert response.status_code == HTTPStatus.OK
        assert response.data == sample_pdf
        assert response.mimetype == "application/pdf"
        assert response.headers["Content-Disposition"] == (
            f"inline; filename={download_name}"
        )

    parameters = connection.execute.call_args.args[1]
    assert parameters == {"id": 3, "uid": 7}


@pytest.mark.parametrize(
    ("link", "download_name"),
    [
        ("private-version", "private-version.pdf"),
        ("private-version.pdf", "private-version.pdf"),
        ("private-version.PDF", "private-version.PDF"),
    ],
)
def test_get_version_downloads_pdf_for_valid_secret_link(
    route_app, sample_pdf, tmp_path, link, download_name
):
    version_path = tmp_path / "version.pdf"
    version_path.write_bytes(sample_pdf)

    engine = route_app.extensions["tatou-db"]
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.first.return_value = SimpleNamespace(
        link=link,
        path=str(version_path),
    )

    with route_app.test_client().get(f"/api/get-version/{link}") as response:
        assert response.status_code == HTTPStatus.OK
        assert response.mimetype == "application/pdf"
        assert response.data == sample_pdf
        assert response.headers["Content-Disposition"] == (
            f"inline; filename={download_name}"
        )

    parameters = connection.execute.call_args.args[1]
    assert parameters == {"link": link}


def test_list_versions_returns_versions():
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.connect.return_value.__enter__.return_value
    query_result = MagicMock()
    query_result.all.return_value = [
        SimpleNamespace(
            id=4,
            documentid=3,
            link="version-link",
            intended_for="bob",
            secret="secret",
            method="eof",
        )
    ]
    connection.execute.return_value = query_result

    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    response = app.test_client().get(
        "/api/list-versions/3",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json == {
        "versions": [
            {
                "id": 4,
                "documentid": 3,
                "link": "version-link",
                "intended_for": "bob",
                "secret": "secret",
                "method": "eof",
            }
        ]
    }


def test_version_lists_do_not_mix_users_with_same_login():
    app = create_app()
    engine = create_engine("sqlite://")
    app.extensions["tatou-db"] = engine

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE Users (id INTEGER, login TEXT)"))
        connection.execute(text("CREATE TABLE Documents (id INTEGER, ownerid INTEGER)"))
        connection.execute(
            text(
                "CREATE TABLE Versions (id INTEGER, documentid INTEGER, link TEXT, "
                "intended_for TEXT, secret TEXT, method TEXT)"
            )
        )
        connection.execute(text("INSERT INTO Users VALUES (1, 'alice'), (2, 'alice')"))
        connection.execute(text("INSERT INTO Documents VALUES (10, 1), (20, 2)"))
        connection.execute(
            text(
                "INSERT INTO Versions VALUES "
                "(11, 10, 'link-a', 'a', 'secret-a', 'eof'), "
                "(21, 20, 'link-b', 'b', 'secret-b', 'eof')"
            )
        )

    client = app.test_client()
    for user_id, own_document_id, other_document_id in ((1, 10, 20), (2, 20, 10)):
        with app.app_context():
            token = create_token(user_id, "alice", f"user{user_id}@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        own_versions = client.get(
            f"/api/list-versions/{own_document_id}", headers=headers
        )
        other_versions = client.get(
            f"/api/list-versions/{other_document_id}", headers=headers
        )
        all_versions = client.get("/api/list-all-versions", headers=headers)

        assert own_versions.status_code == 200
        own_payload = own_versions.get_json()
        assert isinstance(own_payload, dict)
        assert [version["documentid"] for version in own_payload["versions"]] == [
            own_document_id
        ]
        assert other_versions.status_code == 200
        assert other_versions.json == {"versions": []}
        assert all_versions.status_code == 200
        all_payload = all_versions.get_json()
        assert isinstance(all_payload, dict)
        assert [version["documentid"] for version in all_payload["versions"]] == [
            own_document_id
        ]

    engine.dispose()


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("POST", "/api/upload-document"),
        ("DELETE", "/api/delete-document"),
        ("POST", "/api/delete-document"),
        ("DELETE", "/api/delete-document/<document_id>"),
    ],
)
def test_write_document_route_is_registered(method, route):
    app = create_app()
    available_routes = {
        (available_method, rule.rule)
        for rule in app.url_map.iter_rules()
        for available_method in rule.methods or ()
    }

    assert (method, route) in available_routes


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/upload-document"),
        ("DELETE", "/api/delete-document"),
        ("POST", "/api/delete-document"),
        ("DELETE", "/api/delete-document/1"),
    ],
)
def test_write_document_route_requires_token(method, path):
    response = create_app().test_client().open(path, method=method)

    assert response.status_code == 401
    assert response.json == {"error": "Missing or invalid Authorization header"}


def test_upload_document_confines_unsafe_filename(tmp_path):
    app = create_app()
    app.config["STORAGE_DIR"] = tmp_path
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.begin.return_value.__enter__.return_value

    document_id_result = MagicMock()
    document_id_result.scalar.return_value = 3

    document_result = MagicMock()
    document_result.one.return_value = SimpleNamespace(
        id=3,
        name="payload.pkl",
        creation=dt.datetime(2026, 9, 26, 12, 0),
        sha256_hex="ABC123",
        size=7,
    )

    connection.execute.side_effect = [
        MagicMock(),
        document_id_result,
        document_result,
    ]

    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    response = app.test_client().post(
        "/api/upload-document",
        data={"file": (io.BytesIO(b"payload"), "../../payload.pkl")},
        headers={"Authorization": f"Bearer {token}"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201

    insert_parameters = connection.execute.call_args_list[0].args[1]
    stored_path = Path(insert_parameters["path"]).resolve()
    expected_directory = (tmp_path / "files" / "7").resolve()

    assert insert_parameters["name"] == "payload.pkl"
    assert stored_path.parent == expected_directory
    assert stored_path.name.endswith("__payload.pkl")
    assert stored_path.read_bytes() == b"payload"


def test_delete_document_deletes_database_record(tmp_path):
    app = create_app()
    app.config["STORAGE_DIR"] = tmp_path
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    select_connection = engine.connect.return_value.__enter__.return_value
    select_result = MagicMock()
    select_result.first.return_value = SimpleNamespace(
        id=3,
        path="missing.pdf",
    )
    select_connection.execute.return_value = select_result

    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    response = app.test_client().delete(
        "/api/delete-document/3",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json == {
        "deleted": True,
        "id": 3,
        "file_deleted": False,
        "file_missing": True,
        "note": None,
    }
    select_statement, select_parameters = select_connection.execute.call_args.args
    assert "ownerid = :uid" in str(select_statement)
    assert select_parameters == {"id": 3, "uid": 7}

    delete_connection = engine.begin.return_value.__enter__.return_value
    delete_statement, delete_parameters = delete_connection.execute.call_args.args
    assert "ownerid = :uid" in str(delete_statement)
    assert delete_parameters == {"id": 3, "uid": 7}


def test_delete_document_rejects_another_users_document():
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    select_connection = engine.connect.return_value.__enter__.return_value
    select_result = MagicMock()
    select_result.first.return_value = None
    select_connection.execute.return_value = select_result

    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    response = app.test_client().delete(
        "/api/delete-document/3",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json == {"error": "document not found"}

    select_statement, select_parameters = select_connection.execute.call_args.args
    assert "ownerid = :uid" in str(select_statement)
    assert select_parameters == {"id": 3, "uid": 7}
    engine.begin.assert_not_called()


# TODO: Test that missing and malformed delete-document IDs return 400.
# TODO: Test that document database failures return 500.
# TODO: Test that missing or invalid backing-file paths return 500.
