"""Implementation of a PDF watermarking algorithm"""

import io
import os
from random import Random
from typing import Final

import numpy
import pymupdf
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from PIL import Image
from reedsolo import ReedSolomonError, RSCodec
from scipy import fft

from .method import InvalidKeyError, PdfSource, SecretNotFoundError, WatermarkingMethod
from .utils import load_pdf_bytes

TILE_SIZE = 128
SHIFT = 20.0
PAYLOAD_LENGTH = 1024  # Payload size in bits


def _sanity_check_inputs(secret: str, key: str):
    """Check watermarking params for sanity"""

    if len(secret) == 0:
        raise ValueError("The secret must not be empty")
    if len(secret) > 114:
        raise ValueError("The secret is too long (max 114 characters)")

    if len(key) == 0:
        raise ValueError("The key must not be empty")


def _derive_key(key: str, prng: Random) -> bytes:
    """Derive a 32B key from the given secret using Argon2id"""

    argon = Argon2id(
        salt=prng.randbytes(16), length=32, iterations=1, lanes=4, memory_cost=65536
    )
    return argon.derive(key.encode())


def _prepare_payload(derived_key: bytes, nonce: bytes, secret: str) -> bytes:
    """Prepare payload from derived_key and secret for embedding"""

    rscodec = RSCodec()

    padding_length = int((PAYLOAD_LENGTH / 8) - 4 - len(secret) - rscodec.nsym)
    if padding_length < 0:
        raise ValueError("The provided secret is too long")

    # Encrypt with ChaCha20
    cipher = Cipher(
        algorithm=algorithms.ChaCha20(key=derived_key, nonce=nonce),
        mode=None,
    )
    encryptor = cipher.encryptor()
    cipherdata: bytes = (
        encryptor.update((0xCC).to_bytes())  # Header to signal beginning of cleartext
        + encryptor.update(
            numpy.uint16(len(secret)).tobytes()
        )  # Secret length as uint16
        + encryptor.update(secret.encode())
        + encryptor.update(os.urandom(padding_length))  # Random padding
        + encryptor.finalize()
    )

    # Apply RS ECC
    # Insert clear 0xCC header to signal payload start
    return bytes(rscodec.encode((0xCC).to_bytes() + cipherdata))


def _extract_secret(derived_key: bytes, nonce: bytes, payload: bytes) -> str:
    """Extract secret from payload using derived key"""

    rscodec = RSCodec()
    try:
        corrected_payload = bytes(rscodec.decode(payload)[0])
    except ReedSolomonError as e:
        raise SecretNotFoundError() from e

    if corrected_payload[0] != 0xCC:
        raise SecretNotFoundError()

    cipher = Cipher(
        algorithm=algorithms.ChaCha20(key=derived_key, nonce=nonce),
        mode=None,
    )
    decryptor = cipher.decryptor()
    decrypted_bytes = decryptor.update(corrected_payload[1:]) + decryptor.finalize()

    if decrypted_bytes[0] != 0xCC:
        raise InvalidKeyError()

    secret_length = numpy.frombuffer(decrypted_bytes[1:3], dtype=numpy.uint16)[0]
    return (decrypted_bytes[3 : secret_length + 3]).decode()


def _extract_page(document: pymupdf.Document, page_index: int) -> numpy.ndarray:
    """Extract YCbCr data of document page"""

    pixmap_rgb: pymupdf.Pixmap = document.get_page_pixmap(
        page_index, dpi=300, colorspace="rgb"
    )
    array_rgb: numpy.ndarray = numpy.reshape(
        numpy.frombuffer(pixmap_rgb.samples, dtype=numpy.uint8),
        shape=(pixmap_rgb.height, pixmap_rgb.width, pixmap_rgb.n),
    )
    pillow_rgb: Image = Image.fromarray(array_rgb, mode="RGB")

    return numpy.array(pillow_rgb.convert("YCbCr"))


class WatermarkingSoenke(WatermarkingMethod):
    """Implementation of a PDF watermarking algorithm"""

    name: Final[str] = "watermarking-soenke"

    @staticmethod
    def get_usage() -> str:
        """Print usage information"""

        return ""

    def add_watermark(
        self,
        pdf: PdfSource,
        secret: str,
        key: str,
        _: str | None = None,
    ) -> bytes:
        """Add watermark to PDF"""

        _sanity_check_inputs(secret, key)

        # Create local PRNG seeded with key
        prng = Random()
        prng.seed(key)

        derived_key: bytes = _derive_key(key, prng)
        nonce: bytes = prng.randbytes(16)

        # Prepare payload
        payload: bytes = _prepare_payload(derived_key, nonce, secret)

        # Initialize pymupdf document from given file
        pdfbytes = load_pdf_bytes(pdf)
        document: pymupdf.Document = pymupdf.open(stream=pdfbytes, filetype="pdf")

        if document.page_count == 0:
            raise ValueError("The PDF must have at least one page")

        # Process all pages in PDF
        for page_index in range(document.page_count):
            # Convert page to multi-dimensional pixel array
            pagearray: numpy.ndarray = _extract_page(document, page_index)
            height, width, _ = pagearray.shape

            # Iterate over tiles in image
            for y in range(0, height - TILE_SIZE, TILE_SIZE):
                for x in range(0, width - TILE_SIZE, TILE_SIZE):
                    # Extract fixed-size tile from luminance channel
                    tile = (
                        pagearray[y : y + TILE_SIZE, x : x + TILE_SIZE, 0]
                        .copy()
                        .astype(float)
                    )

                    # 2D DCT
                    coefficients: numpy.ndarray = fft.dctn(
                        tile, norm="ortho", axes=[0, 1]
                    )

                    # Modify random coefficients based on bits in payload
                    for byte in payload:
                        for bit_index in range(8):
                            u1 = prng.randint(16, 48)
                            v1 = prng.randint(16, 48)
                            u2 = prng.randint(16, 48)
                            v2 = prng.randint(16, 48)

                            avg = (coefficients[u1][v1] + coefficients[u2][v2]) / 2.0

                            payload_bit = (byte >> bit_index) & 1

                            coefficients[u1][v1] = (
                                avg + SHIFT if payload_bit else avg - SHIFT
                            )
                            coefficients[u2][v2] = (
                                avg - SHIFT if payload_bit else avg + SHIFT
                            )

                    # 2D IDCT
                    reconstructed_tile: numpy.ndarray = fft.idctn(
                        coefficients,
                        norm="ortho",
                        axes=[0, 1],
                    )

                    # Insert reconstructed tile into page
                    pagearray[y : y + TILE_SIZE, x : x + TILE_SIZE, 0] = numpy.clip(
                        reconstructed_tile, 0, 255
                    ).astype(numpy.uint8)

            # Reconstruct page and replace in document
            pagebytes = io.BytesIO()
            Image.fromarray(pagearray, mode="YCbCr").convert("RGB").save(
                pagebytes, format="PNG"
            )
            document.new_page(page_index).insert_image(
                rect=document[page_index].rect, stream=pagebytes
            )
            document.delete_page(page_index + 1)

        return document.tobytes()

    def is_watermark_applicable(
        self,
        pdf: PdfSource,
        position: str | None = None,
    ) -> bool:
        """Check if watermark can be applied to PDF"""

        pdfbytes = load_pdf_bytes(pdf)
        document: pymupdf.Document = pymupdf.open(stream=pdfbytes, filetype="pdf")

        return document.page_count != 0

    def read_secret(self, pdf: PdfSource, key: str) -> str:
        """Extract the secret if present"""

        if len(key) == 0:
            raise ValueError("The key must not be empty")

        # Create local PRNG seeded with key
        prng = Random()
        prng.seed(key)

        derived_key: bytes = _derive_key(key, prng)
        nonce: bytes = prng.randbytes(16)

        # Initialize pymupdf document from given file
        pdfbytes = load_pdf_bytes(pdf)
        document: pymupdf.Document = pymupdf.open(stream=pdfbytes, filetype="pdf")

        if document.page_count == 0:
            raise ValueError("The PDF must have at least one page")

        page_secrets = []

        # Process all pages in PDF
        for page_index in range(document.page_count):
            # Convert page to multi-dimensional pixel array
            pagearray: numpy.ndarray = _extract_page(document, page_index)
            height, width, _ = pagearray.shape

            tile_bits = []

            # Iterate over tiles in image
            for y in range(0, height - TILE_SIZE, TILE_SIZE):
                for x in range(0, width - TILE_SIZE, TILE_SIZE):
                    # Extract fixed-size tile from luminance channel
                    tile = pagearray[y : y + TILE_SIZE, x : x + TILE_SIZE, 0].astype(
                        float
                    )

                    # 2D DCT
                    coefficients: numpy.ndarray = fft.dctn(
                        tile, norm="ortho", axes=[0, 1]
                    )

                    # Sample tile
                    bits = []
                    for _ in range(PAYLOAD_LENGTH):
                        u1 = prng.randint(16, 48)
                        v1 = prng.randint(16, 48)
                        u2 = prng.randint(16, 48)
                        v2 = prng.randint(16, 48)

                        bits.append(
                            1 if coefficients[u1][v1] > coefficients[u2][v2] else 0
                        )
                    tile_bits.append(bits)

            # Average bits over page
            aggregated_bits = (numpy.mean(tile_bits, axis=0) > 0.5).astype(int)

            # Convert bits to bytes
            byte_array = bytearray()
            for i in range(0, len(aggregated_bits), 8):
                byte = 0
                for bit_index, bit in enumerate(aggregated_bits[i : i + 8]):
                    byte |= bit << bit_index
                byte_array.append(byte)

            try:
                page_secrets.append(
                    _extract_secret(derived_key, nonce, bytes(byte_array))
                )
            except SecretNotFoundError():
                if document.page_count != 1:
                    continue
                raise

        # Check if secrets are the same across pages
        page_secrets.sort()
        if page_secrets[0] == page_secrets[-1] and len(page_secrets[0]):
            return page_secrets[0]

        raise SecretNotFoundError()


__all__ = ["WatermarkingSoenke"]
