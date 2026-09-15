from app import create_app
from server import app as old_app


def check_healthz(app):
    response = app.test_client().get("/healthz")

    assert response.status_code == 200
    assert response.is_json
    assert response.json["message"] == "The server is up and running."


def test_old_healthz():
    check_healthz(old_app)


def test_new_healthz():
    check_healthz(create_app())