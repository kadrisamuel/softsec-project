from app import create_app


def test_documents_blueprint_is_registered():
    app = create_app()

    assert "documents" in app.blueprints
