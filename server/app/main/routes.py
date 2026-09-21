from flask import current_app

from . import bp


@bp.get("/")
def home():
    return current_app.send_static_file("index.html")


@bp.get("/<path:filename>")
def static_files(filename):
    return current_app.send_static_file(filename)
