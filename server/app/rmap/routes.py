"""Implementation of the RMAP endpoints"""

from http import HTTPStatus

import rmap
from flask import jsonify, request

from . import bp

# Read private key pass from secret file
with open("/run/secrets/private_key_pass", encoding="utf8") as pass_file:
    private_key_pass = pass_file.read().strip()

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

    _, expected_link, response2 = rmap_server.receiveMsg2(request.get_json())
    # TODO: Create and register watermarked PDF, return link
    return jsonify(response2), HTTPStatus.OK
