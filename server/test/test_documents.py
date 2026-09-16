import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

from app import create_app
from app.auth.tokens import create_token
from server import app as old_app


def test_documents_blueprint_is_registered():
    app = create_app()

    assert "documents" in app.blueprints


def test_list_documents_preserves_missing_token_response():
    for application in (old_app, create_app()):
        response = application.test_client().get("/api/list-documents")

        assert response.status_code == 401
        assert response.json == {
            "error": "Missing or invalid Authorization header"
        }


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
