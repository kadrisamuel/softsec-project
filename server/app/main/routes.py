"""Main blueprint routes"""

from flask import current_app

from . import bp


@bp.get("/")
def home():
    """Handle requests to service root"""

    return current_app.send_static_file("index.html")


@bp.get("/<path:filename>")
def static_files(filename):
    """Serve static files"""

    return current_app.send_static_file(filename)
