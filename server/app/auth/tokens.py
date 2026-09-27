"""Auth token functions"""

from functools import wraps

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

        # TODO: Parse the auth scheme case-insensitively and reject
        # malformed headers
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth.split(" ", 1)[1].strip()

        try:
            data = _serializer().loads(
                token,
                max_age=current_app.config["TOKEN_TTL_SECONDS"],
            )
        except SignatureExpired:
            return jsonify({"error": "Token expired"}), 401
        except BadSignature:
            return jsonify({"error": "Invalid token"}), 401

        # TODO: Validate the token payload fields and their types
        g.user = {
            "id": int(data["uid"]),
            "login": data["login"],
            "email": data.get("email"),
        }
        return view(*args, **kwargs)

    return wrapper
