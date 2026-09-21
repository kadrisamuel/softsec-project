from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL
from flask import current_app

def init_app(app) -> None:
    app.extensions["tatou-db"] = create_engine(db_url(app), pool_pre_ping=True) # pool_pre_ping=True for stale connection protection

def db_url(app) -> URL:
    url = URL.create(
          "mysql+pymysql",
          username=app.config["DB_USER"],
          password=app.config["DB_PASSWORD"],
          host=app.config["DB_HOST"],
          port=app.config["DB_PORT"],
          database=app.config["DB_NAME"],
          query={"charset": "utf8mb4"})
    return url


# Good to know for testing:
# get_engine() requires a Flask application context. It works automatically inside routes. 
# Outside routes, such as scripts or tests, use:
#   with app.app_context():
#       engine = get_engine()
def get_engine() -> Engine:
    return current_app.extensions["tatou-db"]