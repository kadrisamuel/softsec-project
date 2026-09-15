from flask import jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from . import bp
from ..db import get_engine


@bp.post("/create-user")
def create_user():
    # TODO: Validate the request body is JSON object, validate email,
    # define password requirements
    payload = request.get_json(silent=True) or {}
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
    except Exception as error:
        # TODO: Log exception and return a generic error. 
        # Currently exposing database details to the client.
        return jsonify({"error": f"database error: {str(error)}"}), 503

    return jsonify(
        {"id": user.id, "email": user.email, "login": user.login}
    ), 201
