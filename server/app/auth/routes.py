"""Auth blueprint routes"""

from http import HTTPStatus

from flask import current_app, jsonify, request
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_engine
from . import bp
from .tokens import create_token


class CreateUserModel(BaseModel):
    """Pydantic model for create user requests"""

    email: EmailStr
    login: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
    )
    password: str = Field(min_length=8, max_length=64)

    @field_validator("email", "login", mode="before")
    @classmethod
    def strip_strings(cls, value):
        """Remove surrounding spaces from string"""

        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("email", mode="before")
    @classmethod
    def lower_strings(cls, value):
        """Lower-case string"""

        if isinstance(value, str):
            return value.lower()
        return value


class LoginModel(BaseModel):
    """Pydantic model for login requests"""

    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value):
        """Remove surrounding spaces and lower email"""

        if isinstance(value, str):
            return value.strip().lower()
        return value


def _validation_error_message(error: ValidationError, required_message: str) -> str:
    """Choose an error message in missing, login, password, email order."""

    errors = error.errors()
    if any(e["type"] == "missing" for e in errors):
        return required_message

    if any(
        "login" in e["loc"]
        and e["type"]
        in {"string_too_long", "string_too_short", "string_pattern_mismatch"}
        for e in errors
    ):
        return (
            "login must be 1-64 characters using letters, numbers, "
            "periods, underscores, or hyphens"
        )

    if any(
        "password" in e["loc"] and e["type"] in {"string_too_long", "string_too_short"}
        for e in errors
    ):
        return "password must be between 8-64 characters long"

    if any("email" in e["loc"] and e["type"] == "value_error" for e in errors):
        return "email is malformed"

    return "Request body is malformed"


@bp.post("/create-user")
def create_user():
    """Create new service user"""

    # Check basic payload sanity
    if not request.is_json:
        return jsonify(
            {"error": "Content-Type must be application/json"}
        ), HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(
            {"error": "Request body must be a JSON object"}
        ), HTTPStatus.BAD_REQUEST

    # Check payload against model
    try:
        validated_data = CreateUserModel.model_validate(payload)
    except ValidationError as val_err:
        message = _validation_error_message(
            val_err, "email, login, and password are required"
        )
        return jsonify({"error": message}), HTTPStatus.BAD_REQUEST

    password_hash = generate_password_hash(validated_data.password)

    try:
        with get_engine().begin() as connection:
            result = connection.execute(
                text(
                    "INSERT INTO Users (email, hpassword, login) "
                    "VALUES (:email, :password_hash, :login)"
                ),
                {
                    "email": validated_data.email,
                    "password_hash": password_hash,
                    "login": validated_data.login,
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

    # Check payload against model
    try:
        validated_data = LoginModel.model_validate(payload)
    except ValidationError as val_err:
        message = _validation_error_message(val_err, "email and password are required")
        return jsonify({"error": message}), HTTPStatus.BAD_REQUEST

    try:
        with get_engine().connect() as connection:
            user = connection.execute(
                text(
                    "SELECT id, email, login, hpassword "
                    "FROM Users WHERE email = :email LIMIT 1"
                ),
                {"email": validated_data.email},
            ).first()
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("DB error during login")
        return jsonify({"error": "Login failed"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if not user or not check_password_hash(user.hpassword, validated_data.password):
        return jsonify({"error": "invalid credentials"}), HTTPStatus.UNAUTHORIZED

    token = create_token(int(user.id), user.login, user.email)
    return jsonify(
        {
            "token": token,
            "token_type": "bearer",  # nosec: B105
            "expires_in": current_app.config["TOKEN_TTL_SECONDS"],
        }
    ), HTTPStatus.OK
