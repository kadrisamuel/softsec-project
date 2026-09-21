from flask import Blueprint


bp = Blueprint("documents", __name__, url_prefix="/api")

from . import routes
