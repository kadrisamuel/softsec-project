import numpy as np
import pymupdf

from app.watermarking.rgb_dft_qim.key_schedule import derive_keys
from app.watermarking.rgb_dft_qim.message_codec import (
    decode_message,
    encode_message,
)
from app.watermarking.rgb_dft_qim.pdf_carrier import (
    _tile_slices,
    embed_bytes_in_pdf,
    extract_bytes_from_pdf,
    _render_first_page,
    _majority_vote_bytes,
    _build_image_pdf,
    _render_pages,
    _build_image_pdf_pages,
    _normalize_image,
    _usable_tile_slices,
)
from app.watermarking.rgb_dft_qim.dft_qim import extract_bytes


SECRET = "00112233445566778899aabbccddeeff"
MASTER_KEY = "example-master-key"


def _create_test_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=300, height=300)

    page.draw_rect(
        pymupdf.Rect(20, 20, 280, 190),
        fill=(0.2, 0.6, 0.3),
    )
    page.insert_text(
        (45, 140),
        "Watermark test document",
        fontsize=18,
        color=(1, 1, 1),
    )
    page.insert_text(
        (45, 230),
        "Text and image-like regions",
        fontsize=14,
    )

    pdf = document.tobytes()
    document.close()
    return pdf


def _build_jpeg_pdf(
    image: np.ndarray,
    page_width: float,
    page_height: float,
) -> bytes:
    """Rebuild a page using lossy JPEG compression."""
    height, width = image.shape[:2]
    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB,
        width,
        height,
        image.tobytes(),
        False,
    )
    jpeg = pixmap.tobytes(
        "jpeg",
        jpg_quality=60,
    )

    with pymupdf.open() as document:
        page = document.new_page(
            width=page_width,
            height=page_height,
        )
        page.insert_image(page.rect, stream=jpeg)
        return document.tobytes(
            garbage=4,
            deflate=True,
        )


def test_secret_roundtrip_through_pdf():
    source_pdf = _create_test_pdf()
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    assert watermarked_pdf.startswith(b"%PDF-")

    extracted_message = extract_bytes_from_pdf(
        watermarked_pdf,
        len(message),
        keys.qim_positions,
        keys.qim_dither,
    )

    assert decode_message(
        extracted_message,
        MASTER_KEY,
    ) == SECRET


def test_tile_slices_fill_available_page_area():
    image = np.zeros((1200, 1300, 3), dtype=np.uint8)

    tiles = _tile_slices(image)

    assert len(tiles) == 4

    for row_slice, column_slice in tiles:
        assert row_slice.stop - row_slice.start == 512
        assert column_slice.stop - column_slice.start == 512


def test_message_is_recovered_from_usable_tiles():
    source_pdf = _create_test_pdf()
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    image, _, _ = _render_first_page(watermarked_pdf)
    image = _normalize_image(image)
    usable_tiles = _usable_tile_slices(image)

    assert len(usable_tiles) > 1

    candidates = [
        extract_bytes(
            image[row_slice, column_slice],
            len(message),
            keys.qim_positions,
            keys.qim_dither,
        )
        for row_slice, column_slice in usable_tiles
    ]

    recovered_message = _majority_vote_bytes(
        candidates
    )

    assert decode_message(
        recovered_message,
        MASTER_KEY,
    ) == SECRET


def test_majority_vote_recovers_damaged_bytes():
    candidates = [
        bytes([0b10101010, 0b11110000]),
        bytes([0b10101010, 0b11110000]),
        bytes([0b00101010, 0b11110001]),
    ]

    result = _majority_vote_bytes(candidates)

    assert result == bytes([0b10101010, 0b11110000])


def test_extraction_survives_one_destroyed_tile():
    source_pdf = _create_test_pdf()
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    image, page_width, page_height = _render_first_page(
        watermarked_pdf
    )
    row_slice, column_slice = _tile_slices(image)[0]
    image[row_slice, column_slice] = 0

    damaged_pdf = _build_image_pdf(
        image,
        page_width,
        page_height,
    )

    extracted_message = extract_bytes_from_pdf(
        damaged_pdf,
        len(message),
        keys.qim_positions,
        keys.qim_dither,
    )

    assert decode_message(
        extracted_message,
        MASTER_KEY,
    ) == SECRET


def test_extraction_survives_page_wide_pixel_noise():
    source_pdf = _create_test_pdf()
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    image, page_width, page_height = _render_first_page(
        watermarked_pdf
    )

    random = np.random.default_rng(12345)
    noise = random.integers(
        -8,
        9,
        size=image.shape,
        dtype=np.int16,
    )
    noisy_image = np.clip(
        image.astype(np.int16) + noise,
        0,
        255,
    ).astype(np.uint8)

    damaged_pdf = _build_image_pdf(
        noisy_image,
        page_width,
        page_height,
    )

    extracted_message = extract_bytes_from_pdf(
        damaged_pdf,
        len(message),
        keys.qim_positions,
        keys.qim_dither,
    )

    assert decode_message(
        extracted_message,
        MASTER_KEY,
    ) == SECRET


def test_extraction_survives_jpeg_recompression():
    source_pdf = _create_test_pdf()
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    image, page_width, page_height = _render_first_page(
        watermarked_pdf
    )
    compressed_pdf = _build_jpeg_pdf(
        image,
        page_width,
        page_height,
    )

    extracted_message = extract_bytes_from_pdf(
        compressed_pdf,
        len(message),
        keys.qim_positions,
        keys.qim_dither,
    )

    assert decode_message(
        extracted_message,
        MASTER_KEY,
    ) == SECRET


def _create_multi_page_test_pdf(
    page_count: int,
) -> bytes:
    with pymupdf.open() as document:
        for page_number in range(page_count):
            page = document.new_page(
                width=300,
                height=300,
            )
            page.insert_text(
                (50, 150),
                f"Test page {page_number + 1}",
                fontsize=20,
            )

        return document.tobytes()


def test_watermarking_preserves_all_pages():
    source_pdf = _create_multi_page_test_pdf(2)
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    with pymupdf.open(
        stream=watermarked_pdf,
        filetype="pdf",
    ) as document:
        assert document.page_count == 2


def test_extraction_survives_destroyed_first_page():
    source_pdf = _create_multi_page_test_pdf(3)
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    rendered_pages = _render_pages(watermarked_pdf)
    first_image, _, _ = rendered_pages[0]
    first_image[:] = 0

    damaged_pdf = _build_image_pdf_pages(
        rendered_pages
    )

    extracted_message = extract_bytes_from_pdf(
        damaged_pdf,
        len(message),
        keys.qim_positions,
        keys.qim_dither,
    )

    assert decode_message(
        extracted_message,
        MASTER_KEY,
    ) == SECRET


def test_extraction_survives_page_scaling():
    source_pdf = _create_test_pdf()
    keys = derive_keys(MASTER_KEY)
    message = encode_message(SECRET, MASTER_KEY)

    watermarked_pdf = embed_bytes_in_pdf(
        source_pdf,
        message,
        keys.qim_positions,
        keys.qim_dither,
    )

    image, page_width, page_height = _render_first_page(
        watermarked_pdf
    )
    scaled_pdf = _build_image_pdf(
        image,
        page_width * 0.9,
        page_height * 0.9,
    )

    extracted_message = extract_bytes_from_pdf(
        scaled_pdf,
        len(message),
        keys.qim_positions,
        keys.qim_dither,
    )

    assert decode_message(
        extracted_message,
        MASTER_KEY,
    ) == SECRET


def test_normalization_is_independent_of_uniform_scaling():
    original = np.zeros(
        (1000, 1500, 3),
        dtype=np.uint8,
    )
    scaled = np.zeros(
        (900, 1350, 3),
        dtype=np.uint8,
    )

    normalized_original = _normalize_image(original)
    normalized_scaled = _normalize_image(scaled)

    assert normalized_original.shape == (
        2048,
        3072,
        3,
    )
    assert normalized_scaled.shape == (
        2048,
        3072,
        3,
    )


def test_usable_tile_slices_excludes_blank_tiles():
    image = np.full(
        (1024, 1024, 3),
        255,
        dtype=np.uint8,
    )

    image[:256, :512] = 0

    usable_tiles = _usable_tile_slices(image)

    assert len(usable_tiles) == 1

    row_slice, column_slice = usable_tiles[0]
    assert row_slice == slice(0, 512)
    assert column_slice == slice(0, 512)
