"""Test catalog for Soenke's watermarking"""
# pylint: disable=redefined-outer-name

from random import Random

import pytest
from app.watermarking.method import InvalidKeyError, SecretNotFoundError
from app.watermarking.watermarking_soenke import (
    PAYLOAD_LENGTH,
    WatermarkingSoenke,
    _derive_key,
    _extract_secret,
    _prepare_payload,
    _sanity_check_inputs,
)
from pymupdf import Document, csGRAY
from reedsolo import RSCodec


@pytest.fixture(scope="session")
def secret() -> str:
    """Secret shared between tests"""

    return "test-secret"


@pytest.fixture(scope="session")
def key() -> str:
    """Key shared between tests"""

    return "test-key"


@pytest.fixture(scope="session")
def prng() -> Random:
    """PRNG shared between tests"""

    return Random("test-seed")


@pytest.fixture(scope="session")
def nonce() -> bytes:
    """Nonce shared between tests"""

    return b"ffffffffffffffff"


class TestWatermarkingSoenke:
    """Test catalog for Soenke's watermarking"""

    # ---------- Sanity checking ----------
    def test_sanity_check_correct(self, secret: str, key: str):
        """Check sanity check behavior on correct input"""

        _sanity_check_inputs(secret=secret, key=key)

    def test_sanity_check_empty_secret(self, key: str):
        """Check sanity check behavior on empty secret"""

        with pytest.raises(ValueError):
            _sanity_check_inputs(secret="", key=key)

    def test_sanity_check_empty_key(self, secret: str):
        """Check sanity check behavior on empty key"""

        with pytest.raises(ValueError):
            _sanity_check_inputs(secret=secret, key="")

    # ---------- Key derive ----------
    def test_key_derive(self, key: str, prng: Random):
        """Check derive key return length"""

        derived_key = _derive_key(key, prng)
        assert len(derived_key) == 32

    def test_key_derive_determinism(self, key: str):
        """Check derive key determinism"""

        first_key = _derive_key(key, Random("test-seed"))
        second_key = _derive_key(key, Random("test-seed"))
        assert first_key == second_key

    # ---------- Payload preparation ----------
    def test_payload_prepare(self, key: str, secret: str, nonce: bytes, prng: Random):
        """Test basic payload format"""

        derived_key = _derive_key(key, prng)

        payload = _prepare_payload(derived_key, nonce, secret)
        assert len(payload) == PAYLOAD_LENGTH / 8

        rscodec = RSCodec()
        decoded_payload = bytes(rscodec.decode(payload)[0])
        assert decoded_payload[0] == 0xCC

    # ---------- Secret extraction ----------
    def test_secret_extract(self, key: str, secret: str, nonce: bytes, prng: Random):
        """Test secret extraction from payload"""

        derived_key = _derive_key(key, prng)
        payload = _prepare_payload(derived_key, nonce, secret)

        extracted_secret = _extract_secret(derived_key, nonce, payload)
        assert extracted_secret == secret

    def test_secret_extract_invalid_key(
        self, key: str, secret: str, nonce: bytes, prng: Random
    ):
        """Test secret extraction from payload with invalid key"""

        derived_key = _derive_key(key, prng)
        payload = _prepare_payload(derived_key, nonce, secret)

        with pytest.raises(InvalidKeyError):
            _extract_secret(b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", nonce, payload)

    def test_secret_extract_invalid_payload(self, key: str, nonce: bytes, prng: Random):
        """Test secret extraction from invalid payload"""

        derived_key = _derive_key(key, prng)
        scrambled_payload = prng.randbytes(int(PAYLOAD_LENGTH / 8))

        with pytest.raises(SecretNotFoundError):
            _extract_secret(derived_key, nonce, scrambled_payload)

    # ---------- Roundtrip ----------
    def test_rountrip(self, key: str, secret: str):
        """Test roundtrip watermarking"""

        watermarking = WatermarkingSoenke()
        with open("test/samples/sample_1.pdf", "rb") as pdf:
            watermarked_pdf = watermarking.add_watermark(pdf, secret, key)
        extracted_secret = watermarking.read_secret(watermarked_pdf, key)
        assert extracted_secret == secret

    def test_rountrip_greyscale(self, key: str, secret: str):
        """Test roundtrip watermarking but remove colors from watermarked pdf"""

        watermarking = WatermarkingSoenke()
        with open("test/samples/sample_1.pdf", "rb") as pdf:
            watermarked_bytes = watermarking.add_watermark(pdf, secret, key)
        watermarked_doc = Document(stream=watermarked_bytes)
        for page in watermarked_doc:
            pagemap = page.get_pixmap(dpi=300, colorspace=csGRAY)
            page.clean_contents()
            page.insert_image(page.rect, stream=pagemap.tobytes())
        extracted_secret = watermarking.read_secret(watermarked_doc.tobytes(), key)
        assert extracted_secret == secret
