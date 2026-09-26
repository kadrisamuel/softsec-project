"""Implementation of the RMAP endpoints"""

import os
from http import HTTPStatus
from random import Random

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from flask import current_app, jsonify, request
from sqlalchemy import text

from ..db import get_engine
from ..watermarking.method import WatermarkingError
from ..watermarking.utils import apply_watermark
from . import bp
from .source_document import get_source_document_path


def _read_watermarking_key(app) -> str:
    """Read watermarking master key from secret"""

    with open(app.config["RMAP_WATERMARKING_KEY_PATH"], encoding="utf8") as key_file:
        return key_file.read().strip()


def _derive_key(
    master_key: str, document_id: int, issuer: str, expected_link: str
) -> str:
    """Derives a key for a RMAP requested file encoded as a hex string"""

    argon2id = Argon2id(
        salt=Random(expected_link.encode()).randbytes(16),
        length=32,
        iterations=1,
        lanes=4,
        memory_cost=65536,
    )
    return argon2id.derive(
        master_key.encode()
        + str(document_id).encode()
        + issuer.encode()
        + expected_link.encode()
    ).hex()


def _check_link_collision(expected_link: str) -> bool:
    """Check version table for existing versions"""

    with get_engine().connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM Versions
                WHERE link = :link
                LIMIT 1
                """
            ),
            {"link": expected_link},
        ).first()

    return row is not None


def _register_version(
    document_id: int,
    expected_link: str,
    intended_for: str,
    secret: str,
    method: str,
    path: str,
) -> None:
    """Register new watermarked version in version table"""

    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO Versions
                    (documentid, link, intended_for, secret, method, path)
                VALUES
                    (:documentid, :link, :intended_for, :secret, :method, :path)
                """
            ),
            {
                "documentid": document_id,
                "link": expected_link,
                "intended_for": intended_for,
                "secret": secret,
                "method": method,
                "path": path,
            },
        )


@bp.post("/rmap-initiate")
def rmap_initiate():
    """Process RMAP message 1"""

    _, response1 = current_app.extensions["rmap-server"].receiveMsg1(request.get_json())
    return jsonify(response1), HTTPStatus.OK


@bp.post("/rmap-get-link")
def rmap_get_link():
    """Process RMAP message 2"""

    identity, expected_link, response2 = current_app.extensions[
        "rmap-server"
    ].receiveMsg2(request.get_json())
    document_id = int(current_app.extensions["rmap-document-id"])

    # Check for link collision
    try:
        if _check_link_collision(expected_link):
            current_app.logger.exception(
                "link already exists=%s",
                expected_link,
            )
            return jsonify(
                {"error": "version cannot be created"}
            ), HTTPStatus.INTERNAL_SERVER_ERROR
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while retrieving version link=%s",
            expected_link,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    # Prepare watermarking params
    watermark_key: str = _derive_key(
        _read_watermarking_key(current_app), document_id, identity, expected_link
    )
    secret: str = os.urandom(32).hex()
    method: str = current_app.config["RMAP_WATERMARK_METHOD"]

    # Resolve registered group pdf path
    try:
        source_document_path = get_source_document_path(
            current_app,
            document_id,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "Unable to resolve RMAP source document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "source document unavailable"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    # Watermark group pdf
    try:
        with source_document_path.open("rb") as pdf:
            watermarked_pdf_data = apply_watermark(
                method=method,
                pdf=pdf,
                secret=secret,
                key=watermark_key,
            )
    except (WatermarkingError, ValueError):
        return jsonify(
            {"error": "watermarking failed"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR
    except OSError:
        current_app.logger.exception(
            "Unable to read RMAP source document id=%s",
            document_id,
        )
        return jsonify(
            {"error": "source document unavailable"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    # Write watermarked pdf to storage
    out_path = f"{current_app.config['STORAGE_DIR'].resolve()}/{expected_link}.pdf"
    with open(out_path, "wb") as out_pdf:
        out_pdf.write(watermarked_pdf_data)

    # Register new version
    try:
        _register_version(
            document_id=document_id,
            expected_link=expected_link,
            intended_for=identity,
            secret=secret,
            method=method,
            path=out_path,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while creating version with link=%s",
            expected_link,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(response2), HTTPStatus.OK
