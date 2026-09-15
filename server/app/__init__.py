from flask import Flask
from .config import Config
from . import db

# Could 
def create_app(config_class=Config):
    app = Flask(__name__)

    # --- Config ---
    app.config.from_object(config_class)

    db.init_app(app)

    return app