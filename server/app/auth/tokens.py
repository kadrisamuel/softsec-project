"""Auth token functions"""

from functools import wraps
from http import HTTPStatus

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _serializer() -> URLSafeTimedSerializer:
    """Initialize serializer with key and salt"""

    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=current_app.config["SALT"],
    )


def create_token(user_id: int, login: str, email: str) -> str:
    """Create token from user, login, and email"""

    # TODO: Evaluate token revocation and signing key rotation
    return _serializer().dumps({"uid": user_id, "login": login, "email": email})


def require_auth(view):
    """View for authentication enforcement"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        """Verify token validity"""

        if (
            request.authorization is None
            or request.authorization.token is None
            or request.authorization.type != "bearer"
        ):
            return jsonify(
                {"error": "Missing or invalid Authorization header"}
            ), HTTPStatus.UNAUTHORIZED

        try:
            data = _serializer().loads(
                request.authorization.token,
                max_age=current_app.config["TOKEN_TTL_SECONDS"],
            )
        except SignatureExpired:
            return jsonify({"error": "Token expired"}), HTTPStatus.UNAUTHORIZED
        except BadSignature:
            return jsonify({"error": "Invalid token"}), HTTPStatus.UNAUTHORIZED

        # TODO: Validate the token payload fields and their types
        g.user = {
            "id": int(data["uid"]),
            "login": data["login"],
            "email": data.get("email"),
        }
        return view(*args, **kwargs)

    return wrapper
