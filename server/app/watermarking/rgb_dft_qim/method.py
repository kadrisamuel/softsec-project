from __future__ import annotations

import re
from typing import Final

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
            r"[0-9a-fA-F]{32}", secret
        ) is None:
            raise ValueError(
                "Secret must contain exactly 32 hexadecimal characters"
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
        load_pdf_bytes(pdf)

        # Remain unavailable until embedding is implemented.
        return False

    def add_watermark(
        self,
        pdf: PdfSource,
        secret: str,
        key: str,
        position: str | None = None,
    ) -> bytes:
        load_pdf_bytes(pdf)
        self._validate_secret(secret)
        self._validate_key(key)

        raise WatermarkingError(
            "RGB DFT-QIM embedding is not implemented yet"
        )

    def read_secret(self, pdf: PdfSource, key: str) -> str:
        load_pdf_bytes(pdf)
        self._validate_key(key)

        raise SecretNotFoundError(
            "RGB DFT-QIM extraction is not implemented yet"
        )


__all__ = ["RGBDFTQIMWatermark"]
