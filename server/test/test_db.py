from unittest.mock import MagicMock

from app import create_app, db


class TestConfig:
    TESTING = True
    DB_USER = "test-user"
    DB_PASSWORD = "test-password"
    DB_HOST = "test-host"
    DB_PORT = 3307
    DB_NAME = "test-database"


def test_create_app_initializes_database(monkeypatch):
    fake_engine = object()
    mocked_create_engine = MagicMock(return_value=fake_engine)
    monkeypatch.setattr(db, "create_engine", mocked_create_engine)

    app = create_app(TestConfig)

    assert app.extensions["tatou-db"] is fake_engine

    mocked_create_engine.assert_called_once()
    url = mocked_create_engine.call_args.args[0]
    options = mocked_create_engine.call_args.kwargs

    assert url.drivername == "mysql+pymysql"
    assert url.username == "test-user"
    assert url.password == "test-password"
    assert url.host == "test-host"
    assert url.port == 3307
    assert url.database == "test-database"
    assert options["pool_pre_ping"] is True

    with app.app_context():
        assert db.get_engine() is fake_engine