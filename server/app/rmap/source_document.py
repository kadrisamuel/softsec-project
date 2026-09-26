"""Manage the original PDF distributed through RMAP."""

import hashlib
import secrets
from pathlib import Path

from flask import Flask
from sqlalchemy import text
from sqlalchemy.engine import Connection
from werkzeug.security import generate_password_hash

_SYSTEM_OWNER_EMAIL = "rmap-system@local.invalid"
_SYSTEM_OWNER_LOGIN = "rmap-system"


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


def _ensure_system_owner(connection: Connection) -> int:
    """Create or find the internal owner used for the RMAP document."""

    unusable_password = generate_password_hash(
        secrets.token_urlsafe(32)
    )

    connection.execute(
        text(
            """
            INSERT INTO Users (email, hpassword, login)
            VALUES (:email, :hpassword, :login)
            ON DUPLICATE KEY UPDATE email = VALUES(email)
            """
        ),
        {
            "email": _SYSTEM_OWNER_EMAIL,
            "hpassword": unusable_password,
            "login": _SYSTEM_OWNER_LOGIN,
        },
    )

    row = connection.execute(
        text(
            """
            SELECT id
            FROM Users
            WHERE email = :email
            LIMIT 1
            """
        ),
        {"email": _SYSTEM_OWNER_EMAIL},
    ).one()

    return int(row.id)


def _ensure_document(
    connection: Connection,
    *,
    owner_id: int,
    name: str,
    path: Path,
    sha256_hex: str,
    size: int,
) -> int:
    """Create or find the registered RMAP source document."""

    parameters = {
        "name": name,
        "path": str(path),
        "owner_id": owner_id,
        "sha256_hex": sha256_hex,
        "size": size,
    }

    connection.execute(
        text(
            """
            INSERT INTO Documents
                (name, path, ownerid, sha256, size)
            VALUES
                (:name, :path, :owner_id, UNHEX(:sha256_hex), :size)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                ownerid = VALUES(ownerid),
                sha256 = VALUES(sha256),
                size = VALUES(size)
            """
        ),
        parameters,
    )

    row = connection.execute(
        text(
            """
            SELECT id
            FROM Documents
            WHERE path = :path
            LIMIT 1
            """
        ),
        {"path": str(path)},
    ).one()

    return int(row.id)


def ensure_source_document(app: Flask) -> int:
    """Store and register the RMAP source PDF, return its document ID."""

    stored_path, sha256_hex, size = prepare_source_pdf(app)
    engine = app.extensions["tatou-db"]

    with engine.begin() as connection:
        owner_id = _ensure_system_owner(connection)

        document_id = _ensure_document(
            connection,
            owner_id=owner_id,
            name=app.config["RMAP_SOURCE_DOCUMENT_NAME"],
            path=stored_path,
            sha256_hex=sha256_hex,
            size=size,
        )

    return document_id


def get_source_document_path(
    app: Flask,
    document_id: int,
) -> Path:
    """Return the validated storage path for a registered document."""

    engine = app.extensions["tatou-db"]

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT path
                FROM Documents
                WHERE id = :document_id
                LIMIT 1
                """
            ),
            {"document_id": document_id},
        ).first()

    if row is None:
        raise RuntimeError(
            f"RMAP source document {document_id} is not registered"
        )

    storage_root = Path(app.config["STORAGE_DIR"]).resolve()
    document_path = Path(row.path)

    if not document_path.is_absolute():
        document_path = storage_root / document_path

    document_path = document_path.resolve()

    try:
        document_path.relative_to(storage_root)
    except ValueError as exc:
        raise RuntimeError(
            "RMAP source document path escapes storage directory"
        ) from exc

    if not document_path.is_file():
        raise RuntimeError(
            f"RMAP source document file is missing: {document_path}"
        )

    return document_path
