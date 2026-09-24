"""Implementation of the RMAP endpoints"""

from hashlib import sha3_256
from http import HTTPStatus

import rmap
from flask import current_app, jsonify, request

from ..watermarking.method import WatermarkingError
from ..watermarking.utils import apply_watermark
from . import bp

# Read private key pass from secret file
with open("/run/secrets/private_key_pass", encoding="utf8") as pass_file:
    private_key_pass = pass_file.read().strip()

# Use SHA3-256 private key password hex hash as key for watermarking
watermark_key = sha3_256(private_key_pass.encode()).hexdigest()

# Prepare RMAP server
rmap_server = rmap.RMAPServer(
    server_public_key_path="pub-keys/Group_02.asc",
    server_private_key_path="/run/secrets/private_key",
    passphrase=private_key_pass,
)
rmap_server.loadIdentities("pub-keys")


@bp.post("/rmap-initiate")
def rmap_initiate():
    """Process RMAP message 1"""

    _, response1 = rmap_server.receiveMsg1(request.get_json())
    return jsonify(response1), HTTPStatus.OK


@bp.post("/rmap-get-link")
def rmap_get_link():
    """Process RMAP message 2"""

    identity, expected_link, response2 = rmap_server.receiveMsg2(request.get_json())

    # Try watermark group pdf
    with open("/run/secrets/group_pdf", "rb") as pdf:
        try:
            watermarked_pdf_data = apply_watermark(
                "toy-eof", pdf, secret=identity, key=watermark_key
            )  # TODO: Replace with final watermarking
        except (WatermarkingError, ValueError):
            return jsonify(
                {"error": "watermarking failed"}
            ), HTTPStatus.INTERNAL_SERVER_ERROR

    # Write watermarked pdf to storage
    with open(f"{current_app.config["STORAGE_DIR"].resolve()}/{identity}.pdf", "wb") as out_pdf:
        out_pdf.write(watermarked_pdf_data)

    # TODO: Register watermarked PDF, return link

    return jsonify(response2), HTTPStatus.OK
