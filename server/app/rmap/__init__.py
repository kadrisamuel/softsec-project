from flask import Blueprint


bp = Blueprint("rmap", __name__, url_prefix="/api")

from . import routes
