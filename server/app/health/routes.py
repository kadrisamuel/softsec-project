from http import HTTPStatus

from flask import current_app, jsonify
from sqlalchemy import text

from ..db import get_engine
from . import bp


@bp.get("/healthz")
def healthz():
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("Database health check failed")
        db_ok = False

    return jsonify(
        {
            "message": "The server is up and running.",
            "db_connected": db_ok,
        }
    ), HTTPStatus.OK
