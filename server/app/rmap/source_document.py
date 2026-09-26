"""Manage the original PDF distributed through RMAP."""

import hashlib
import os
from pathlib import Path


def prepare_source_pdf(app) -> tuple[Path, str, int]:
    """Validate and store the RMAP source PDF.

    Returns its stored path, SHA-256 hash and size.
    """

    source_path = Path(app.config["RMAP_SOURCE_PDF_PATH"])

    try:
        data = source_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read RMAP source PDF: {source_path}"
        ) from exc

    if not data.startswith(b"%PDF-"):
        raise RuntimeError("RMAP source document is not a valid PDF")

    sha256_hex = hashlib.sha256(data).hexdigest()
    target_directory = (
        Path(app.config["STORAGE_DIR"])
        / "rmap"
        / "originals"
    )
    target_path = target_directory / f"{sha256_hex}.pdf"

    target_directory.mkdir(parents=True, exist_ok=True)

    if not target_path.exists():
        target_path.write_bytes(data)

    return target_path, sha256_hex, len(data)