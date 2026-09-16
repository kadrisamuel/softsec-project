from flask import Flask
from .config import Config
from . import db


def create_app(config_class=Config):
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

    return app
