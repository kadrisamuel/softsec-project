from flask import Flask
from .config import Config
from . import db


def create_app(config_class=Config):
    app = Flask(__name__)

    # --- Config ---
    app.config.from_object(config_class)

    db.init_app(app)

    # Register blueprints
    from .main import bp as main_bp
    app.register_blueprint(main_bp)

    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    return app
