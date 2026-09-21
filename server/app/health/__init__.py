from flask import Blueprint

bp = Blueprint("health", __name__)

from . import routes
