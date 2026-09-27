"""Watermarking blueprint initialization"""

from flask import Blueprint


bp = Blueprint("watermarking", __name__, url_prefix="/api")

from . import routes  # pylint: disable=wrong-import-position
