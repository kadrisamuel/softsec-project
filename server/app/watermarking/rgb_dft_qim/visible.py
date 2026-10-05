"""Build and draw the visible identifier on RGB page images."""

from __future__ import annotations

import hmac

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_IDENTIFIER_BYTES = 8
_FONT_SIZE = 48
_TEXT_OPACITY = 48
_ROTATION_DEGREES = 30
_STAMP_PADDING = 24
_HORIZONTAL_GAP = 120
_VERTICAL_GAP = 80


def visible_identifier(
    secret: str,
    visible_key: bytes,
) -> str:
    """Return a short keyed identifier without exposing the secret."""
    digest = hmac.digest(
        visible_key,
        b"visible-identifier:" + bytes.fromhex(secret),
        "sha256",
    )

    fingerprint = digest[
        :_IDENTIFIER_BYTES
    ].hex().upper()

    return f"TATOU-{fingerprint}"


def _keyed_offset(
    key: bytes,
    label: bytes,
    modulus: int,
) -> int:
    digest = hmac.digest(
        key,
        b"visible-placement:" + label,
        "sha256",
    )
    return int.from_bytes(
        digest[:8],
        byteorder="big",
    ) % modulus


def add_visible_pattern(
    image: np.ndarray,
    identifier: str,
    placement_key: bytes,
) -> np.ndarray:
    """Burn a repeated keyed diagonal identifier into an RGB image."""
    font = ImageFont.load_default(
        size=_FONT_SIZE
    )

    measuring_image = Image.new(
        "RGBA",
        (1, 1),
    )
    measuring_draw = ImageDraw.Draw(
        measuring_image
    )
    bounds = measuring_draw.textbbox(
        (0, 0),
        identifier,
        font=font,
    )

    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]

    stamp = Image.new(
        "RGBA",
        (
            int(text_width + 2 * _STAMP_PADDING),
            int(text_height + 2 * _STAMP_PADDING),
        ),
        (0, 0, 0, 0),
    )
    stamp_draw = ImageDraw.Draw(stamp)
    stamp_draw.text(
        (
            _STAMP_PADDING - bounds[0],
            _STAMP_PADDING - bounds[1],
        ),
        identifier,
        font=font,
        fill=(20, 20, 20, _TEXT_OPACITY),
    )

    stamp = stamp.rotate(
        _ROTATION_DEGREES,
        expand=True,
        resample=Image.Resampling.BICUBIC,
    )

    base = Image.fromarray(image).convert("RGBA")
    overlay = Image.new(
        "RGBA",
        base.size,
        (0, 0, 0, 0),
    )

    horizontal_spacing = (
        stamp.width + _HORIZONTAL_GAP
    )
    vertical_spacing = (
        stamp.height + _VERTICAL_GAP
    )
    offset_x = _keyed_offset(
        placement_key,
        b"x",
        horizontal_spacing,
    )
    offset_y = _keyed_offset(
        placement_key,
        b"y",
        vertical_spacing,
    )

    row_positions = range(
        offset_y - vertical_spacing,
        image.shape[0] + vertical_spacing,
        vertical_spacing,
    )

    for row_index, top in enumerate(row_positions):
        row_shift = (
            horizontal_spacing // 2
            if row_index % 2
            else 0
        )

        for left in range(
            offset_x - horizontal_spacing - row_shift,
            image.shape[1] + horizontal_spacing,
            horizontal_spacing,
        ):
            overlay.alpha_composite(
                stamp,
                (left, top),
            )

    result = Image.alpha_composite(
        base,
        overlay,
    ).convert("RGB")

    return np.asarray(
        result,
        dtype=np.uint8,
    ).copy()


__all__ = ["visible_identifier", "add_visible_pattern"]
