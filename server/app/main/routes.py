from flask import current_app, jsonify
from sqlalchemy import text

from . import bp
from ..db import get_engine


@bp.get("/")
def home():
    return current_app.send_static_file("index.html")


@bp.get("/<path:filename>")
def static_files(filename):
    return current_app.send_static_file(filename)


@bp.get("/healthz")
def healthz():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"message": "The server is up and running.", "db_connected": db_ok}), 200
