from flask import current_app, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from . import bp
from .tokens import create_token
from ..db import get_engine


@bp.post("/create-user")
def create_user():
    # TODO: Validate email, define password requirements
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    email = (payload.get("email") or "").strip().lower()
    login = (payload.get("login") or "").strip()
    password = payload.get("password") or ""
    if not email or not login or not password:
        return jsonify({"error": "email, login, and password are required"}), 400

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
        return jsonify({"error": "email or login already exists"}), 409
    except Exception:
        current_app.logger.exception("DB error while creating user")
        return jsonify({"error": "user creation failed"}), 500

    return jsonify(
        {"id": user.id, "email": user.email, "login": user.login}
    ), 201


@bp.post("/login")
def login():
    # TODO: Add rate limiting for failed login attempts
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    try:
        with get_engine().connect() as connection:
            user = connection.execute(
                text(
                    "SELECT id, email, login, hpassword "
                    "FROM Users WHERE email = :email LIMIT 1"
                ),
                {"email": email},
            ).first()
    except Exception as error:
        current_app.logger.exception("DB error during login")
        return jsonify({"error": "Login failed"}), 500

    if not user or not check_password_hash(user.hpassword, password):
        return jsonify({"error": "invalid credentials"}), 401

    token = create_token(int(user.id), user.login, user.email)
    return jsonify(
        {
            "token": token,
            "token_type": "bearer",
            "expires_in": current_app.config["TOKEN_TTL_SECONDS"],
        }
    ), 200
