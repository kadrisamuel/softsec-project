"""Utility functions and registry for PDF watermarking methods"""

from .add_after_eof import AddAfterEOF
from .method import (
    PdfSource,
    WatermarkingMethod,
)
from .rgb_dft_qim.method import RGBDFTQIMWatermark
from .watermarking_soenke import WatermarkingSoenke

# --------------------
# Method registry
# --------------------

METHODS: dict[str, WatermarkingMethod] = {
    AddAfterEOF.name: AddAfterEOF(),
    RGBDFTQIMWatermark.name: RGBDFTQIMWatermark(),
    WatermarkingSoenke.name: WatermarkingSoenke(),
}

"""Registry of available watermarking methods.

Keys are human-readable method names (stable, lowercase, hyphenated)
exposed by each implementation's ``.name`` attribute. Values are
*instances* of the corresponding class.
"""


# def register_method(method: WatermarkingMethod) -> None:
#     """Register (or replace) a watermarking method instance by name."""
#     METHODS[method.name] = method


def get_method(method: str | WatermarkingMethod) -> WatermarkingMethod:
    """Resolve a method from a string name or pass-through an instance.

    Raises
    ------
    KeyError
        If ``method`` is a string not present in :data:`METHODS`.
    """
    if isinstance(method, WatermarkingMethod):
        return method
    try:
        return METHODS[method]
    except KeyError as exc:
        raise KeyError(
            f"Unknown watermarking method: {method!r}. Known: {sorted(METHODS)}"
        ) from exc


# --------------------
# Public API helpers
# --------------------


def apply_watermark(
    method: str | WatermarkingMethod,
    pdf: PdfSource,
    secret: str,
    key: str,
    position: str | None = None,
) -> bytes:
    """Apply a watermark using the specified method and return new PDF bytes."""
    m = get_method(method)
    return m.add_watermark(pdf=pdf, secret=secret, key=key, position=position)


def is_watermarking_applicable(
    method: str | WatermarkingMethod,
    pdf: PdfSource,
    position: str | None = None,
) -> bool:
    """Check whether the watermarking method is applicable to the specified PDF."""
    m = get_method(method)
    return m.is_watermark_applicable(pdf=pdf, position=position)


def read_watermark(method: str | WatermarkingMethod, pdf: PdfSource, key: str) -> str:
    """Recover a secret from ``pdf`` using the specified method."""
    m = get_method(method)
    return m.read_secret(pdf=pdf, key=key)


__all__ = [
    "METHODS",
    "apply_watermark",
    "get_method",
    "is_watermarking_applicable",
    "read_watermark",
]
