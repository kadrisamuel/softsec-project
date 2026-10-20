from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.rmap import bp as rmap_blueprint
from app.rmap.routes import _derive_key


@pytest.fixture(scope="session")
def master_key() -> str:
    return "test-master-key"


def test_rmap_derive_key_length(master_key):  # mutmut identified
    key = _derive_key(master_key, 100, "TestIssuer", "expected-link")
    assert len(key) == 64


def test_rmap_key_derive_deterministic(master_key):
    first_key = _derive_key(master_key, 100, "TestIssuer", "expected-link")
    second_key = _derive_key(master_key, 100, "TestIssuer", "expected-link")
    assert first_key == second_key


def test_rmap_initiate_returns_protocol_response():
    request_payload = {"message": "test-initiate", "values": [1, 2, 3]}
    response_payload = {"message": "test-response", "challenge": "challenge-value"}
    rmap_server = MagicMock()
    rmap_server.receiveMsg1.return_value = (
        {"internal-state": "not-the-response"},
        response_payload,
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.extensions["rmap-server"] = rmap_server
    app.register_blueprint(rmap_blueprint)

    response = app.test_client().post(
        "/api/rmap-initiate",
        json=request_payload,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json == response_payload
    rmap_server.receiveMsg1.assert_called_once_with(request_payload)
