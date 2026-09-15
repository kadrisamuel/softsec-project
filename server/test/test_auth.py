from app import create_app


def test_auth_blueprint_is_registered():
    app = create_app()

    assert "auth" in app.blueprints
