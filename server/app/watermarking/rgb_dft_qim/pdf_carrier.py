from __future__ import annotations

import numpy as np
import pymupdf

from .dft_qim import embed_bytes, extract_bytes


_RENDER_DPI = 300
_BLOCK_SIZE = 512


def _render_first_page(
    pdf: bytes,
) -> tuple[np.ndarray, float, float]:
    with pymupdf.open(
        stream=pdf,
        filetype="pdf",
    ) as document:
        if document.page_count == 0:
            raise ValueError("PDF must contain at least one page")

        page = document[0]
        page_width = page.rect.width
        page_height = page.rect.height

        pixmap = page.get_pixmap(
            dpi=_RENDER_DPI,
            colorspace=pymupdf.csRGB,
            alpha=False,
        )

        image = np.frombuffer(
            pixmap.samples,
            dtype=np.uint8,
        ).reshape(
            pixmap.height,
            pixmap.width,
            3,
        ).copy()

    return image, page_width, page_height


def _center_slices(
    image: np.ndarray,
) -> tuple[slice, slice]:
    height, width = image.shape[:2]

    if height < _BLOCK_SIZE or width < _BLOCK_SIZE:
        raise ValueError(
            "Rendered page must be at least 512 by 512 pixels"
        )

    top = (height - _BLOCK_SIZE) // 2
    left = (width - _BLOCK_SIZE) // 2

    return (
        slice(top, top + _BLOCK_SIZE),
        slice(left, left + _BLOCK_SIZE),
    )


def _build_image_pdf(
    image: np.ndarray,
    page_width: float,
    page_height: float,
) -> bytes:
    """Rebuilds the modified RGB image as a one-page PDF."""
    height, width = image.shape[:2]

    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB,
        width,
        height,
        image.tobytes(),
        False,
    )
    png_bytes = pixmap.tobytes("png")

    with pymupdf.open() as document:
        page = document.new_page(
            width=page_width,
            height=page_height,
        )
        page.insert_image(
            page.rect,
            stream=png_bytes,
        )

        return document.tobytes(
            garbage=4,
            deflate=True,
        )


def embed_bytes_in_pdf(
    pdf: bytes,
    data: bytes,
    position_key: bytes,
    dither_key: bytes,
) -> bytes:
    image, page_width, page_height = _render_first_page(pdf)
    row_slice, column_slice = _center_slices(image)

    block = image[
        row_slice,
        column_slice,
    ].copy()

    watermarked_block = embed_bytes(
        block,
        data,
        position_key,
        dither_key,
    )

    image[
        row_slice,
        column_slice,
    ] = watermarked_block

    return _build_image_pdf(
        image,
        page_width,
        page_height,
    )


def extract_bytes_from_pdf(
    pdf: bytes,
    byte_count: int,
    position_key: bytes,
    dither_key: bytes,
) -> bytes:
    image, _, _ = _render_first_page(pdf)
    row_slice, column_slice = _center_slices(image)

    block = image[
        row_slice,
        column_slice,
    ]

    return extract_bytes(
        block,
        byte_count,
        position_key,
        dither_key,
    )


def is_pdf_compatible(pdf: bytes) -> bool:
    try:
        image, _, _ = _render_first_page(pdf)
        _center_slices(image)
    except (ValueError, pymupdf.FileDataError):
        return False

    return True


__all__ = ["embed_bytes_in_pdf", "extract_bytes_from_pdf", "is_pdf_compatible"]
