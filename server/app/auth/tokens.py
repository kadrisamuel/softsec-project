from flask import current_app
from itsdangerous import URLSafeTimedSerializer


def create_token(user_id: int, login: str, email: str) -> str:
    # TODO: Evaluate token revocation and signing key rotation
    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="tatou-auth",
    )
    return serializer.dumps(
        {"uid": user_id, "login": login, "email": email}
    )
