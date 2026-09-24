import pytest

# pyrefly: ignore [missing-import]
from app.watermarking.rgb_dft_qim.method import RGBDFTQIMWatermark


VALID_SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def method():
    return RGBDFTQIMWatermark()


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "0" * 31,
        "0" * 33,
        "g" * 32,
        "A" * 32,
        123,
        None,
    ],
)
def test_secret_validation_rejects_invalid_values(method, secret):
    with pytest.raises(
        ValueError,
        match="exactly 32 hexadecimal characters"
    ):
        method._validate_secret(secret)

    
@pytest.mark.parametrize(
    "secret",
    [
        VALID_SECRET,
    ],
)
def test_secret_validation_accepts_hex_values(method, secret):
    method._validate_secret(secret)


@pytest.mark.parametrize("key", ["", 123, None])
def test_key_validation_rejects_invalid_values(method, key):
    with pytest.raises(ValueError, match="non-empty string"):
        method._validate_key(key)


def test_key_validation_accepts_non_empty_string(method):
    method._validate_key("test-key")
