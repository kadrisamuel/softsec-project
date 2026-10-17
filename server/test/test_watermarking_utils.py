import pytest
from app.watermarking.add_after_eof import AddAfterEOF
from app.watermarking.rgb_dft_qim.method import RGBDFTQIMWatermark
from app.watermarking.utils import (
    apply_watermark,
    get_method,
    is_watermarking_applicable,
    read_watermark,
)
from app.watermarking.watermarking_soenke import WatermarkingSoenke


@pytest.fixture
def secret() -> str:
    return "f" * 32


@pytest.fixture
def key() -> str:
    return "test-key"


@pytest.mark.parametrize(
    "method", [AddAfterEOF, RGBDFTQIMWatermark, WatermarkingSoenke]
)
def test_get_method_known(method):
    assert isinstance(get_method(method()), method)
    assert isinstance(get_method(method.name), method)


def test_get_method_unknown():
    with pytest.raises(KeyError):
        get_method("UnknownMethod")


@pytest.mark.parametrize(
    "method",
    [
        AddAfterEOF.name,
        AddAfterEOF(),
        RGBDFTQIMWatermark.name,
        RGBDFTQIMWatermark(),
        WatermarkingSoenke.name,
        WatermarkingSoenke(),
    ],
)
def test_watermark_apply(method, secret, key):
    with open("test/samples/sample_1.pdf", "rb") as pdf:
        out_bytes = apply_watermark(method, pdf, secret, key)
        assert isinstance(out_bytes, (bytes, bytearray))
        assert out_bytes.startswith(b"%PDF-")


def test_watermark_apply_unknown(secret, key):
    with open("test/samples/sample_1.pdf", "rb") as pdf, pytest.raises(KeyError):
        apply_watermark("UnknownMethod", pdf, secret, key)


@pytest.mark.parametrize(
    "method",
    [
        AddAfterEOF.name,
        AddAfterEOF(),
        RGBDFTQIMWatermark.name,
        RGBDFTQIMWatermark(),
        WatermarkingSoenke.name,
        WatermarkingSoenke(),
    ],
)
def test_watermark_applicable(method):
    with open("test/samples/sample_1.pdf", "rb") as pdf:
        assert is_watermarking_applicable(method, pdf)


def test_watermark_applicable_unknown():
    with open("test/samples/sample_1.pdf", "rb") as pdf, pytest.raises(KeyError):
        assert is_watermarking_applicable("UnknownMethod", pdf)


@pytest.mark.parametrize(
    "method",
    [
        AddAfterEOF.name,
        AddAfterEOF(),
        RGBDFTQIMWatermark.name,
        RGBDFTQIMWatermark(),
        WatermarkingSoenke.name,
        WatermarkingSoenke(),
    ],
)
def test_watermark_roundtrip(method, secret, key):
    with open("test/samples/sample_1.pdf", "rb") as pdf:
        out_bytes = apply_watermark(method, pdf, secret, key)
        assert read_watermark(method, out_bytes, key) == secret


def test_read_watermark_unknown(key):
    with open("test/samples/sample_1.pdf", "rb") as pdf, pytest.raises(KeyError):
        read_watermark("UnknownMethod", pdf, key)
