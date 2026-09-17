from flask import current_app, jsonify
from sqlalchemy import text

from . import bp
from ..db import get_engine


@bp.get("/healthz")
def healthz():
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        current_app.logger.exception("Database health check failed")
        db_ok = False

    return jsonify(
        {
            "message": "The server is up and running.",
            "db_connected": db_ok,
        }
    ), 200
