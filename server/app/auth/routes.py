"""Auth blueprint routes"""

import re
from http import HTTPStatus

from flask import current_app, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_engine
from . import bp
from .tokens import create_token

_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@bp.post("/create-user")
def create_user():
    """Create new service user"""

    # TODO: Validate email
    if not request.is_json:
        return jsonify(
            {"error": "Content-Type must be application/json"}
        ), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Request body must be a JSON object"}
        ), HTTPStatus.BAD_REQUEST

    email = (payload.get("email") or "").strip().lower()
    login = (payload.get("login") or "").strip()
    password = payload.get("password") or ""
    if not email or not login or not password:
        return jsonify(
            {"error": "email, login, and password are required"}
        ), HTTPStatus.BAD_REQUEST

    if _LOGIN_RE.fullmatch(login) is None:
        return jsonify(
            {
                "error": (
                    "login must be 1-64 characters using letters, numbers, "
                    "periods, underscores, or hyphens"
                )
            }
        ), HTTPStatus.BAD_REQUEST

    password_hash = generate_password_hash(password)

    try:
        with get_engine().begin() as connection:
            result = connection.execute(
                text(
                    "INSERT INTO Users (email, hpassword, login) "
                    "VALUES (:email, :password_hash, :login)"
                ),
                {
                    "email": email,
                    "password_hash": password_hash,
                    "login": login,
                },
            )
            user_id = int(result.lastrowid)
            user = connection.execute(
                text("SELECT id, email, login FROM Users WHERE id = :id"),
                {"id": user_id},
            ).one()
    except IntegrityError:
        return jsonify({"error": "email or login already exists"}), HTTPStatus.CONFLICT
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("DB error while creating user")
        return jsonify(
            {"error": "user creation failed"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(
        {"id": user.id, "email": user.email, "login": user.login}
    ), HTTPStatus.CREATED


@bp.post("/login")
def login_user():
    """Login for existing service user"""

    # TODO: Add rate limiting for failed login attempts
    if not request.is_json:
        return jsonify(
            {"error": "Content-Type must be application/json"}
        ), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Request body must be a JSON object"}
        ), HTTPStatus.BAD_REQUEST
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        return jsonify(
            {"error": "email and password are required"}
        ), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            user = connection.execute(
                text(
                    "SELECT id, email, login, hpassword "
                    "FROM Users WHERE email = :email LIMIT 1"
                ),
                {"email": email},
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("DB error during login")
        return jsonify({"error": "Login failed"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if not user or not check_password_hash(user.hpassword, password):
        return jsonify({"error": "invalid credentials"}), HTTPStatus.UNAUTHORIZED

    token = create_token(int(user.id), user.login, user.email)
    return jsonify(
        {
            "token": token,
            "token_type": "bearer",  # nosec: 105
            "expires_in": current_app.config["TOKEN_TTL_SECONDS"],
        }
    ), HTTPStatus.OK
