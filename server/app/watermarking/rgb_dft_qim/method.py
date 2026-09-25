from __future__ import annotations

import re
from typing import Final

from .key_schedule import derive_keys
from .message_codec import (
    ENCODED_MESSAGE_BYTES,
    decode_message,
    encode_message,
)
from .pdf_carrier import (
    embed_bytes_in_pdf,
    extract_bytes_from_pdf,
    is_pdf_compatible,
)
from .visible import visible_identifier

from ..method import (
    PdfSource,
    SecretNotFoundError,
    WatermarkingError,
    WatermarkingMethod,
    load_pdf_bytes,
)


class RGBDFTQIMWatermark(WatermarkingMethod):
    """Raster watermark using RGB frequency-domain embedding"""

    name: Final[str] = "rgb-dft-qim-v1"

    @staticmethod
    def get_usage() -> str:
        return (
            "Embeds a 32-character hexadecimal secret into a PDF. "
            "The position parameter will later accept JSON configuration."
        )

    @staticmethod
    def _validate_secret(secret: str) -> None:
        """The secret is the information embedded in the PDF and recovered later. 
        Here, it is a 128-bit watermark identifier represented by 32 hex characters"""
        if not isinstance(secret, str) or re.fullmatch(
            r"[0-9a-f]{32}", secret
        ) is None:
            raise ValueError(
                "Secret must contain exactly 32 lowercase hexadecimal characters"
            )

    @staticmethod
    def _validate_key(key: str) -> None:
        """The key controls where and how the watermark is embedded. 
        It is used to calculate values for: 
        * QIM coefficient positions
        * Pilot pattern
        * Bit interleaving
        * HMAC authentication
        * Visible mark placement"""
        if not isinstance(key, str) or not key:
            raise ValueError("Key must be a non-empty string")

    def is_watermark_applicable(
        self,
        pdf: PdfSource,
        position: str | None = None,
    ) -> bool:
        data = load_pdf_bytes(pdf)
        return is_pdf_compatible(data)

    def add_watermark(
        self,
        pdf: PdfSource,
        secret: str,
        key: str,
        position: str | None = None,
    ) -> bytes:
        data = load_pdf_bytes(pdf)
        self._validate_secret(secret)
        self._validate_key(key)

        if not is_pdf_compatible(data):
            raise WatermarkingError(
                "PDF page is too small for RGB DFT-QIM"
            )

        keys = derive_keys(key)
        message = encode_message(secret, key)

        visible_text = visible_identifier(
            secret,
            keys.visible_placement,
        )

        return embed_bytes_in_pdf(
            data,
            message,
            keys.qim_positions,
            keys.qim_dither,
            visible_text=visible_text,
            visible_key=keys.visible_placement,
        )

    def read_secret(self, pdf: PdfSource, key: str) -> str:
        data = load_pdf_bytes(pdf)
        self._validate_key(key)

        if not is_pdf_compatible(data):
            raise SecretNotFoundError(
                "PDF is not compatible with RGB DFT-QIM"
            )

        keys = derive_keys(key)

        try:
            message = extract_bytes_from_pdf(
                data,
                ENCODED_MESSAGE_BYTES,
                keys.qim_positions,
                keys.qim_dither,
            )
            return decode_message(message, key)
        except ValueError as exc:
            raise SecretNotFoundError(
                "RGB DFT-QIM watermark was not found"
            ) from exc


__all__ = ["RGBDFTQIMWatermark"]
