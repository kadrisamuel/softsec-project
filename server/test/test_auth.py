import time
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app import create_app
from app.auth.tokens import create_token, require_auth
from flask import g
from itsdangerous import URLSafeTimedSerializer
from pymysql import DatabaseError
from werkzeug.security import check_password_hash, generate_password_hash


@pytest.fixture
def auth_app():
    """Simple app instance with db engine and no-transaction assert"""

    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    yield app

    engine.begin.assert_not_called()


def test_auth_blueprint_is_registered():
    app = create_app()

    assert "auth" in app.blueprints


def test_create_user_unsupported_media(auth_app):
    response = auth_app.test_client().post("/api/create-user", data="test")

    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert response.json == {"error": "Content-Type must be application/json"}


def test_create_user_not_json(auth_app):
    response = auth_app.test_client().post(
        "/api/create-user", data="test", content_type="application/json"
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body must be a JSON object"}


def test_create_user_preserves_missing_fields_response(auth_app):
    response = auth_app.test_client().post("/api/create-user", json={})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "email, login, and password are required"}


@pytest.mark.parametrize(
    "endpoint, payload, expected_message",
    [
        (
            "/api/create-user",
            {"email": "invalid", "login": "../plugins"},
            "email, login, and password are required",
        ),
        (
            "/api/create-user",
            {"email": "invalid", "login": "../plugins", "password": "short"},
            (
                "login must be 1-64 characters using letters, numbers, "
                "periods, underscores, or hyphens"
            ),
        ),
        (
            "/api/create-user",
            {"email": "invalid", "login": "alice", "password": "short"},
            "password must be between 8-64 characters long",
        ),
        (
            "/api/login",
            {"email": "invalid"},
            "email and password are required",
        ),
        (
            "/api/login",
            {"email": "invalid", "password": "short"},
            "password must be between 8-64 characters long",
        ),
    ],
)
def test_validation_preserves_error_priority(
    auth_app, endpoint, payload, expected_message
):
    response = auth_app.test_client().post(endpoint, json=payload)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": expected_message}


@pytest.mark.parametrize("login_length", [0, 65])
def test_create_user_rejects_login_oob(auth_app, login_length):  # mumut identified
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": "user@example.com",
            "login": "a" * login_length,
            "password": "test-password",
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {
        "error": (
            "login must be 1-64 characters using letters, numbers, "
            "periods, underscores, or hyphens"
        )
    }


def test_create_user_rejects_login_with_path_separator(auth_app):
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": "user@example.com",
            "login": "../plugins",
            "password": "test-password",
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {
        "error": (
            "login must be 1-64 characters using letters, numbers, "
            "periods, underscores, or hyphens"
        )
    }


def test_create_user_rejects_incorrect_login_type(auth_app):
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": "user@exmaple.com",
            "login": 1234,
            "password": "test-password",
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body is malformed"}


def test_create_user_rejects_invalid_email(auth_app):
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": "user@example",
            "login": "alice",
            "password": "test-password",
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "email is malformed"}


def test_create_user_rejects_incorrect_email_type(auth_app):
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": 1234,
            "login": "alice",
            "password": "test-password",
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body is malformed"}


@pytest.mark.parametrize("password_length", [7, 65])
def test_create_user_rejects_password_oob(auth_app, password_length):
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": "user@example.com",
            "login": "alice",
            "password": "x" * password_length,
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "password must be between 8-64 characters long"}


def test_create_user_rejects_incorrect_password_type(auth_app):
    response = auth_app.test_client().post(
        "/api/create-user",
        json={
            "email": "user@example.com",
            "login": "alice",
            "password": 1234,
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body is malformed"}


def test_create_user_db_error():
    app = create_app()
    engine = MagicMock()
    engine.execute.side_effect = DatabaseError()
    app.extensions["tatou-db"] = engine

    response = (
        create_app()
        .test_client()
        .post(
            "/api/create-user",
            json={
                "email": "user@example.com",
                "login": "alice",
                "password": "test-password",
            },
        )
    )

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json == {"error": "user creation failed"}


@pytest.mark.parametrize("password", ["test-password", "x" * 8, "x" * 64])
def test_create_user_creates_user(password):
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.begin.return_value.__enter__.return_value
    insert_result = SimpleNamespace(lastrowid=7)
    select_result = MagicMock()
    select_result.one.return_value = SimpleNamespace(
        id=7,
        email="user@example.com",
        login="alice",
    )
    connection.execute.side_effect = [insert_result, select_result]

    response = app.test_client().post(
        "/api/create-user",
        json={
            "email": " User@Example.com ",
            "login": "alice",
            "password": password,
        },
    )

    assert response.status_code == 201
    assert response.json == {
        "id": 7,
        "email": "user@example.com",
        "login": "alice",
    }

    insert_parameters = connection.execute.call_args_list[0].args[1]
    assert insert_parameters["email"] == "user@example.com"
    assert check_password_hash(
        insert_parameters["password_hash"],
        password,
    )


def test_create_token_preserves_authentication_payload():
    app = create_app()

    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    serializer = URLSafeTimedSerializer(
        app.config["SECRET_KEY"],
        salt=app.config["SALT"],
    )
    payload = serializer.loads(
        token,
        max_age=app.config["TOKEN_TTL_SECONDS"],
    )

    assert payload == {
        "uid": 7,
        "login": "alice",
        "email": "user@example.com",
    }


def test_login_unsupported_media(auth_app):
    response = auth_app.test_client().post("/api/login", data="test")

    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert response.json == {"error": "Content-Type must be application/json"}


def test_login_not_json(auth_app):
    response = auth_app.test_client().post(
        "/api/login", data="test", content_type="application/json"
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body must be a JSON object"}


def test_login_preserves_missing_fields_response(auth_app):
    response = auth_app.test_client().post("/api/login", json={})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "email and password are required"}


def test_login_invalid_email(auth_app):
    response = auth_app.test_client().post(
        "/api/login", json={"email": "user@example", "password": "test-password"}
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "email is malformed"}


def test_login_invalid_email_type(auth_app):
    response = auth_app.test_client().post(
        "/api/login", json={"email": 1234, "password": "test-password"}
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body is malformed"}


@pytest.mark.parametrize("password_length", [7, 65])
def test_login_password_oob(auth_app, password_length):
    response = auth_app.test_client().post(
        "/api/login",
        json={"email": "user@example.com", "password": "x" * password_length},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "password must be between 8-64 characters long"}


def test_login_invalid_password_type(auth_app):
    response = auth_app.test_client().post(
        "/api/login", json={"email": "user@example.com", "password": 1234}
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json == {"error": "Request body is malformed"}


@pytest.mark.parametrize("password", ["test-password", "x" * 8, "x" * 64])
def test_login_returns_token_for_valid_credentials(password):
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.connect.return_value.__enter__.return_value
    select_result = MagicMock()
    select_result.first.return_value = SimpleNamespace(
        id=7,
        email="user@example.com",
        login="alice",
        hpassword=generate_password_hash(password),
    )
    connection.execute.return_value = select_result

    response = app.test_client().post(
        "/api/login",
        json={"email": "user@example.com", "password": password},
    )

    assert response.status_code == 200
    assert response.json["token_type"] == "bearer"
    assert response.json["expires_in"] == app.config["TOKEN_TTL_SECONDS"]
    assert response.json["token"]


def test_login_rejects_invalid_credentials():
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.connect.return_value.__enter__.return_value
    select_result = MagicMock()
    select_result.first.return_value = None
    connection.execute.return_value = select_result

    response = app.test_client().post(
        "/api/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json == {"error": "invalid credentials"}


def test_login_db_error():
    app = create_app()
    engine = MagicMock()
    engine.execute.side_effect = DatabaseError()
    app.extensions["tatou-db"] = engine

    response = (
        create_app()
        .test_client()
        .post(
            "/api/login",
            json={"email": "user@example.com", "password": "test-password"},
        )
    )

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json == {"error": "Login failed"}


def add_protected_test_route(app):
    @app.get("/protected-test-route")
    @require_auth
    def protected_test_route():
        return {"user": g.user}


def test_require_auth_rejects_missing_token():
    app = create_app()
    add_protected_test_route(app)

    response = app.test_client().get("/protected-test-route")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json == {"error": "Missing or invalid Authorization header"}


def test_require_auth_rejects_invalid_token():
    app = create_app()
    add_protected_test_route(app)

    response = app.test_client().get(
        "/protected-test-route",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json == {"error": "Invalid token"}


def test_require_auth_rejects_expired_token():
    app = create_app()
    app.config["TOKEN_TTL_SECONDS"] = 1
    add_protected_test_route(app)
    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    time.sleep(3)

    response = app.test_client().get(
        "/protected-test-route",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json == {"error": "Token expired"}


def test_require_auth_accepts_valid_token():
    app = create_app()
    add_protected_test_route(app)
    with app.app_context():
        token = create_token(7, "alice", "user@example.com")

    response = app.test_client().get(
        "/protected-test-route",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json == {
        "user": {
            "id": 7,
            "login": "alice",
            "email": "user@example.com",
        }
    }
