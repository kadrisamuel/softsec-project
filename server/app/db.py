from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from flask import current_app

def db_url() -> str:
    return (
        f"mysql+pymysql://{app.config['DB_USER']}:{app.config['DB_PASSWORD']}"
        f"@{current_app.config['DB_HOST']}:{current_app.config['DB_PORT']}/{current_app.config['DB_NAME']}?charset=utf8mb4"
    )

def get_engine():
    eng = current_app.config.get("_ENGINE")
    if eng is None:
        eng = create_engine(db_url(), pool_pre_ping=True, future=True)
        current_app.config["_ENGINE"] = eng
    return eng