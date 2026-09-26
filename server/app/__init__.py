"""App initialization"""
# pylint: disable=import-outside-toplevel

from flask import Flask

from . import db
from .config import Config
from .rmap import server

rmap_server = server.RMAPServerExtension()


def create_app(config_class=Config):
    """Create flask app"""

    app = Flask(__name__)

    # --- Config ---
    app.config.from_object(config_class)

    db.init_app(app)

    # Register blueprints
    from .health import bp as health_bp

    app.register_blueprint(health_bp)

    if app.config.get("ENABLE_MAIN_ROUTES", False):
        from .main import bp as main_bp

        app.register_blueprint(main_bp)

    if app.config.get("ENABLE_AUTH_ROUTES", False):
        from .auth import bp as auth_bp

        app.register_blueprint(auth_bp)

    if app.config.get("ENABLE_DOCUMENT_ROUTES", False):
        from .documents import bp as documents_bp

        app.register_blueprint(documents_bp)

    if app.config.get("ENABLE_WATERMARKING_ROUTES", False):
        from .watermarking import bp as watermarking_bp

        app.register_blueprint(watermarking_bp)

    if app.config.get("ENABLE_RMAP_ROUTES", False):
        rmap_server.init_app(app)

        from .rmap.source_document import ensure_source_document

        app.extensions["rmap-document-id"] = (
            ensure_source_document(app)
        )

        from .rmap import bp as rmap_bp

        app.register_blueprint(rmap_bp)

    return app
