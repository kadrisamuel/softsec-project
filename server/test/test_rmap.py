import pytest
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
