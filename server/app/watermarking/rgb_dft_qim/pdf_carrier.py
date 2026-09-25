from __future__ import annotations
from PIL import Image

import numpy as np
import pymupdf

from .dft_qim import embed_bytes, extract_bytes


_RENDER_DPI = 300
_BLOCK_SIZE = 512
_NORMALIZED_SHORT_SIDE = 2048
_MIN_TILE_STANDARD_DEVIATION = 8.0


def _render_pages(
    pdf: bytes,
) -> list[tuple[np.ndarray, float, float]]:
    """Render every PDF page as RGB pixels with its original page size."""
    rendered_pages = []

    with pymupdf.open(
        stream=pdf,
        filetype="pdf",
    ) as document:
        if document.page_count == 0:
            raise ValueError("PDF must contain at least one page")

        for page in document:
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

            rendered_pages.append(
                (
                    image,
                    page.rect.width,
                    page.rect.height,
                )
            )

    return rendered_pages


def _render_first_page(
    pdf: bytes,
) -> tuple[np.ndarray, float, float]:
    """Render the first PDF page for single-page operations and tests."""
    return _render_pages(pdf)[0]


def _normalize_image(
    image: np.ndarray,
) -> np.ndarray:
    """Resize an image to a fixed short side while preserving its aspect ratio."""
    height, width = image.shape[:2]
    scale = _NORMALIZED_SHORT_SIDE / min(
        height,
        width,
    )

    target_height = round(height * scale)
    target_width = round(width * scale)

    # Pillow uses (width, height), while NumPy uses
    # (height, width, channels).
    resized = Image.fromarray(image).resize(
        (target_width, target_height),
        resample=Image.Resampling.LANCZOS,
    )

    return np.asarray(
        resized,
        dtype=np.uint8,
    ).copy()


def _tile_slices(
    image: np.ndarray,
) -> list[tuple[slice, slice]]:
    """Divide the image into a centred grid of complete 512×512 tiles."""

    height, width = image.shape[:2]

    row_count = height // _BLOCK_SIZE
    column_count = width // _BLOCK_SIZE

    if row_count == 0 or column_count == 0:
        raise ValueError(
            "Rendered page must be at least 512 by 512 pixels"
        )

    grid_height = row_count * _BLOCK_SIZE
    grid_width = column_count * _BLOCK_SIZE
    top = (height - grid_height) // 2
    left = (width - grid_width) // 2

    return [
        (
            slice(
                top + row * _BLOCK_SIZE,
                top + (row + 1) * _BLOCK_SIZE,
            ),
            slice(
                left + column * _BLOCK_SIZE,
                left + (column + 1) * _BLOCK_SIZE,
            ),
        )
        for row in range(row_count)
        for column in range(column_count)
    ]


def _usable_tile_slices(
    image: np.ndarray,
) -> list[tuple[slice, slice]]:
    """Return tiles containing enough visual variation for reliable QIM."""
    usable_tiles = []

    for row_slice, column_slice in _tile_slices(image):
        block = image[
            row_slice,
            column_slice,
        ]

        if (
            float(np.std(block))
            >= _MIN_TILE_STANDARD_DEVIATION
        ):
            usable_tiles.append(
                (row_slice, column_slice)
            )

    return usable_tiles


def _build_image_pdf_pages(
    pages: list[tuple[np.ndarray, float, float]],
) -> bytes:
    """Rebuild multiple RGB page images as one PDF."""
    with pymupdf.open() as document:
        for image, page_width, page_height in pages:
            height, width = image.shape[:2]
            pixmap = pymupdf.Pixmap(
                pymupdf.csRGB,
                width,
                height,
                image.tobytes(),
                False,
            )
            png_bytes = pixmap.tobytes("png")

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


def _build_image_pdf(
    image: np.ndarray,
    page_width: float,
    page_height: float,
) -> bytes:
    """Rebuild one modified RGB image as a one-page PDF."""
    return _build_image_pdf_pages(
        [(image, page_width, page_height)]
    )


def _majority_vote_bytes(
    candidates: list[bytes],
) -> bytes:
    """Recover bytes by selecting the most common value of each bit."""
    if not candidates:
        raise ValueError("At least one candidate is required")

    byte_count = len(candidates[0])

    if any(len(candidate) != byte_count for candidate in candidates):
        raise ValueError("Candidates must have equal lengths")

    candidate_bits = [
        np.unpackbits(
            np.frombuffer(candidate, dtype=np.uint8)
        )
        for candidate in candidates
    ]

    votes = np.sum(candidate_bits, axis=0)
    majority_bits = votes > len(candidates) / 2

    ties = votes * 2 == len(candidates)
    majority_bits[ties] = candidate_bits[0][ties]

    return np.packbits(majority_bits).tobytes()


def embed_bytes_in_pdf(
    pdf: bytes,
    data: bytes,
    position_key: bytes,
    dither_key: bytes,
) -> bytes:
    rendered_pages = _render_pages(pdf)
    watermarked_pages = []
    for rendered_image, page_width, page_height in rendered_pages:
        image = _normalize_image(rendered_image)

        for row_slice, column_slice in _usable_tile_slices(image):
            block = image[
                row_slice,
                column_slice,
            ].copy()

            image[
                row_slice,
                column_slice,
            ] = embed_bytes(
                block,
                data,
                position_key,
                dither_key,
            )

        watermarked_pages.append(
            (image, page_width, page_height)
        )

    return _build_image_pdf_pages(watermarked_pages)


def extract_bytes_from_pdf(
    pdf: bytes,
    byte_count: int,
    position_key: bytes,
    dither_key: bytes,
) -> bytes:
    """Extract data by voting across every tile on every page."""
    page_candidates = []

    for rendered_image, _, _ in _render_pages(pdf):
        image = _normalize_image(rendered_image)
        tile_candidates = []

        for row_slice, column_slice in _usable_tile_slices(image):
            block = image[
                row_slice,
                column_slice,
            ]

            tile_candidates.append(
                extract_bytes(
                    block,
                    byte_count,
                    position_key,
                    dither_key,
                )
            )

        if tile_candidates:
             page_candidates.append(
                _majority_vote_bytes(tile_candidates)
        )

    return _majority_vote_bytes(page_candidates)


def is_pdf_compatible(pdf: bytes) -> bool:
    try:
        image, _, _ = _render_first_page(pdf)
        _tile_slices(image)
    except (ValueError, pymupdf.FileDataError):
        return False

    return True


__all__ = ["embed_bytes_in_pdf", "extract_bytes_from_pdf", "is_pdf_compatible"]
