import pymupdf

from app.watermarking.rgb_dft_qim.key_schedule import derive_keys
from app.watermarking.rgb_dft_qim.message_codec import (
    decode_message,
    encode_message,
)
from app.watermarking.rgb_dft_qim.pdf_carrier import (
    embed_bytes_in_pdf,
    extract_bytes_from_pdf,
)


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