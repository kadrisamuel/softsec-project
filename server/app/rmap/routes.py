"""Implementation of the RMAP endpoints"""

from hashlib import sha3_256
from http import HTTPStatus

import rmap
from flask import current_app, jsonify, request
from sqlalchemy import text

from ..db import get_engine
from ..watermarking.method import WatermarkingError
from ..watermarking.utils import apply_watermark
from . import bp

# Read private key pass from secret file
with open(
    current_app.config["RMAP_SERVER_PRIVATE_KEY_PASS_FILE"], encoding="utf8"
) as pass_file:
    private_key_pass = pass_file.read().strip()

# Use SHA3-256 private key password hex hash as key for watermarking
watermark_key = sha3_256(private_key_pass.encode()).hexdigest()

# Prepare RMAP server
rmap_server = rmap.RMAPServer(
    server_public_key_path=current_app.config["RMAP_SERVER_PUBLIC_KEY_PATH"],
    server_private_key_path=current_app.config["RMAP_SERVER_PRIVATE_KEY_PATH"],
    passphrase=private_key_pass,
    linkPrefix=current_app.config["RMAP_LINK_PREFIX"],
)
rmap_server.loadIdentities(current_app.config["RMAP_CLIENT_KEYS_DIR"])


@bp.post("/rmap-initiate")
def rmap_initiate():
    """Process RMAP message 1"""

    _, response1 = rmap_server.receiveMsg1(request.get_json())
    return jsonify(response1), HTTPStatus.OK


@bp.post("/rmap-get-link")
def rmap_get_link():
    """Process RMAP message 2"""

    identity, expected_link, response2 = rmap_server.receiveMsg2(request.get_json())

    # Check for link collision
    try:
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
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while retrieving version link=%s",
            expected_link,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    if row:
        current_app.logger.exception(
            "link already exists=%s",
            expected_link,
        )
        return jsonify(
            {"error": "version cannot be created"}
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    # Try watermark group pdf
    with open("/run/secrets/group_pdf", "rb") as pdf:
        try:
            watermarked_pdf_data = apply_watermark(
                current_app.config["RMAP_WATERMARK_METHOD"],
                pdf,
                secret=identity,
                key=watermark_key,
            )
        except (WatermarkingError, ValueError):
            return jsonify(
                {"error": "watermarking failed"}
            ), HTTPStatus.INTERNAL_SERVER_ERROR

    # Write watermarked pdf to storage
    out_path = f"{current_app.config['STORAGE_DIR'].resolve()}/{identity}.pdf"
    with open(out_path, "wb") as out_pdf:
        out_pdf.write(watermarked_pdf_data)

    # Register new version
    try:
        with get_engine().begin() as connection:
            row = connection.execute(
                text(
                    """
                    INSERT INTO Versions (documentid, link, secret, method, path)
                    VALUES (:documentid, :link, :secret, :method, :path)
                    """
                ),
                {
                    "documentid": document_id,  # TODO: Insert correct document id
                    "link": expected_link,
                    "secret": identity,
                    "method": current_app.config["RMAP_WATERMARK_METHOD"],
                    "path": out_path,
                },
            )
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception(
            "DB error while creating version with link=%s",
            expected_link,
        )
        return jsonify({"error": "database error"}), HTTPStatus.INTERNAL_SERVER_ERROR

    return jsonify(response2), HTTPStatus.OK
