"""Identify the recipient of an already aligned, watermarked PDF.

Render and tile the PDF once, then try each candidate from versions-dump.txt.
For each candidate, derive its key, compare the extracted watermark with the
expected message, and report any match confirmed by decoding the message.
"""

import ast
from pathlib import Path

import numpy as np
from dotenv import dotenv_values

from list_visible_identifiers import parse_version_rows
from app.rmap.routes import _derive_key
from app.watermarking.rgb_dft_qim.dft_qim import extract_bytes
from app.watermarking.rgb_dft_qim.key_schedule import derive_keys
from app.watermarking.rgb_dft_qim.message_codec import (
    ENCODED_MESSAGE_BYTES,
    decode_message,
    encode_message,
)
from app.watermarking.rgb_dft_qim.pdf_carrier import (
    _majority_vote_bytes,
    _normalize_image,
    _render_pages,
    _usable_tile_slices,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"  # Change this path if your master key is elsewhere.
GROUP_KEYS_FILE = PROJECT_ROOT / "output/attribution/group_key.txt"
UNATTRIBUTED_PDF = PROJECT_ROOT / "output/attribution/aligned.pdf"
DEFAULT_DUMP = PROJECT_ROOT / "scripts/versions-dump.txt"

def prepare_page_tiles(pdf_path: str | Path) -> list[list[np.ndarray]]:
    """Render and normalize once; retain the same tiles used by the method."""
    pages = []
    for rendered_image, _, _ in _render_pages(Path(pdf_path).read_bytes()):
        image = _normalize_image(rendered_image)
        pages.append([
            image[row_slice, column_slice]
            for row_slice, column_slice in _usable_tile_slices(image)
        ])
    if not any(pages):
        raise ValueError("PDF has no usable watermark tiles")
    return pages


def extract_message_from_tiles(pages: list[list[np.ndarray]], key: str) -> bytes:
    """Try one key against cached tiles using the method's normal voting."""
    keys = derive_keys(key)
    page_candidates = [
        _majority_vote_bytes([
            extract_bytes(
                tile,
                ENCODED_MESSAGE_BYTES,
                keys.qim_positions,
                keys.qim_dither,
            )
            for tile in tiles
        ])
        for tiles in pages
        if tiles
    ]
    message = _majority_vote_bytes(page_candidates)
    return message


def read_secret_from_tiles(pages, key):
    return decode_message(extract_message_from_tiles(pages, key), key)


pages = prepare_page_tiles(UNATTRIBUTED_PDF)
attempts = 0
matches = 0

master_key = dotenv_values(ENV_FILE).get("WATERMARKING_MASTER_KEY")
if not master_key:
    raise ValueError(f"WATERMARKING_MASTER_KEY is missing from {ENV_FILE}")

for document_id, link, recipient, expected_secret in parse_version_rows(DEFAULT_DUMP):
    print(f"Scoring RMAP candidate {link}", flush=True)
    key = _derive_key(master_key, document_id, recipient, link)
    attempts += 1
    # try:
    #     extracted = read_secret_from_tiles(pages, key)
    #     print(f"extracted {extracted}")
    # except ValueError:
    #     continue
    expected = encode_message(expected_secret, key)
    observed = extract_message_from_tiles(pages, key)

    matching_bits = 424 - sum(
        (a ^ b).bit_count() for a, b in zip(expected, observed)
    )
    wrong_bytes = sum(a != b for a, b in zip(expected, observed))
    print(f"{recipient}: {matching_bits}/424 bits, {wrong_bytes}/53 wrong bytes")

    try:
        extracted = decode_message(observed, key)
    except ValueError:
        continue
    if extracted == expected_secret:
        print(f"MATCH: {recipient} (RMAP copy {link})")
        matches += 1

if not matches:
    print(f"No verified match among {attempts} candidate keys.")
