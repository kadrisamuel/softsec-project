import pytest
import pymupdf

# pyrefly: ignore [missing-import]
from app.watermarking.rgb_dft_qim.method import RGBDFTQIMWatermark
from app.watermarking.utils import METHODS


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
        match="exactly 32 lowercase hexadecimal characters"
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


@pytest.fixture
def sample_pdf():
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=300)
        page.draw_rect(
            pymupdf.Rect(20, 20, 280, 200),
            fill=(0.2, 0.5, 0.8),
        )
        page.insert_text(
            (45, 140),
            "RGB DFT-QIM method test",
            fontsize=18,
            color=(1, 1, 1),
        )
        return document.tobytes()


def test_method_roundtrip(method, sample_pdf):
    key = "example-master-key"

    assert method.is_watermark_applicable(sample_pdf)

    watermarked_pdf = method.add_watermark(
        sample_pdf,
        secret=VALID_SECRET,
        key=key,
    )

    assert method.read_secret(
        watermarked_pdf,
        key=key,
    ) == VALID_SECRET


def test_method_is_registered():
    registered_method = METHODS[RGBDFTQIMWatermark.name]

    assert isinstance(registered_method, RGBDFTQIMWatermark)
