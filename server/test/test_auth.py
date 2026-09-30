from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import g
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from app.auth.tokens import create_token, require_auth


def test_auth_blueprint_is_registered():
    app = create_app()

    assert "auth" in app.blueprints


def test_create_user_preserves_missing_fields_response():
    response = create_app().test_client().post("/api/create-user", json={})

    assert response.status_code == 400
    assert response.json == {
        "error": "email, login, and password are required"
    }


def test_create_user_rejects_login_with_path_separator():
    response = create_app().test_client().post(
        "/api/create-user",
        json={
            "email": "user@example.com",
            "login": "../plugins",
            "password": "test-password",
        },
    )

    assert response.status_code == 400
    assert response.json == {
        "error": (
            "login must be 1-64 characters using letters, numbers, "
            "periods, underscores, or hyphens"
        )
    }


def test_create_user_creates_user():
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
            "password": "test-password",
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
        "test-password",
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


def test_login_preserves_missing_fields_response():
    response = create_app().test_client().post("/api/login", json={})

    assert response.status_code == 400
    assert response.json == {"error": "email and password are required"}


def test_login_returns_token_for_valid_credentials():
    app = create_app()
    engine = MagicMock()
    app.extensions["tatou-db"] = engine

    connection = engine.connect.return_value.__enter__.return_value
    select_result = MagicMock()
    select_result.first.return_value = SimpleNamespace(
        id=7,
        email="user@example.com",
        login="alice",
        hpassword=generate_password_hash("test-password"),
    )
    connection.execute.return_value = select_result

    response = app.test_client().post(
        "/api/login",
        json={"email": "user@example.com", "password": "test-password"},
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

    assert response.status_code == 401
    assert response.json == {"error": "invalid credentials"}


def add_protected_test_route(app):
    @app.get("/protected-test-route")
    @require_auth
    def protected_test_route():
        return {"user": g.user}


def test_require_auth_rejects_missing_token():
    app = create_app()
    add_protected_test_route(app)

    response = app.test_client().get("/protected-test-route")

    assert response.status_code == 401
    assert response.json == {
        "error": "Missing or invalid Authorization header"
    }


def test_require_auth_rejects_invalid_token():
    app = create_app()
    add_protected_test_route(app)

    response = app.test_client().get(
        "/protected-test-route",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json == {"error": "Invalid token"}


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


# TODO: Test that create-user and login database failures return 500.
