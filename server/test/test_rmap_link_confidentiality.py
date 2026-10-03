"""Check selected server-nonce guesses against RMAP link issuance."""

import base64
import json
import re

import pgpy
from flask import Flask
from pgpy.constants import (
    CompressionAlgorithm,
    HashAlgorithm,
    KeyFlags,
    PubKeyAlgorithm,
    SymmetricKeyAlgorithm,
)
from rmap import RMAPServer

import app.rmap.routes as rmap_routes
from app.rmap import bp as rmap_blueprint


def _new_key(name):
    """Make a temporary PGP identity for this isolated integration test."""
    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    key.add_uid(
        pgpy.PGPUID.new(name),
        usage={KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB],
    )
    return key


def _wire_message(server_public_key, body):
    """Create the documented RMAP wire format using only the server public key."""
    encrypted = server_public_key.encrypt(pgpy.PGPMessage.new(json.dumps(body)))
    payload = "".join(
        line
        for line in str(encrypted).splitlines()
        if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", line)
    )
    assert payload
    return {"payload": payload}


def _decrypt_wire_message(private_key, wire_message):
    """Let the test harness inspect the true nonce for its positive control."""
    encrypted = pgpy.PGPMessage.from_blob(
        base64.b64decode(wire_message["payload"], validate=True)
    )
    return json.loads(private_key.decrypt(encrypted).message)


def test_selected_server_nonce_guesses_are_rejected(tmp_path, monkeypatch):
    """Try several guesses on one challenge, then complete that same challenge."""
    identity = "Group_02"
    server_key = _new_key("Server")
    client_key = _new_key(identity)
    server_public_path = tmp_path / "server-public.asc"
    server_private_path = tmp_path / "server-private.asc"
    client_keys_dir = tmp_path / "client-keys"
    client_keys_dir.mkdir()
    server_public_path.write_text(str(server_key.pubkey), encoding="ascii")
    server_private_path.write_text(str(server_key), encoding="ascii")
    (client_keys_dir / f"{identity}.asc").write_text(
        str(client_key.pubkey), encoding="ascii"
    )

    rmap_server = RMAPServer(
        server_public_key_path=server_public_path,
        server_private_key_path=server_private_path,
        passphrase=None,
        linkPrefix="/api/get-version/",
    )
    rmap_server.loadIdentities(client_keys_dir)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n%test document\n")
    registered_links = []

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        STORAGE_DIR=storage_dir,
        RMAP_WATERMARK_METHOD="test",
    )
    app.extensions["rmap-server"] = rmap_server
    app.extensions["rmap-document-id"] = 1
    app.register_blueprint(rmap_blueprint)

    monkeypatch.setattr(rmap_routes, "_check_link_collision", lambda _link: False)
    monkeypatch.setattr(rmap_routes, "_read_watermarking_key", lambda _app: "test")
    monkeypatch.setattr(rmap_routes, "_derive_key", lambda *_args: "test")
    monkeypatch.setattr(
        rmap_routes, "get_source_document_path", lambda _app, _id: source_pdf
    )
    monkeypatch.setattr(
        rmap_routes, "apply_watermark", lambda **_kwargs: source_pdf.read_bytes()
    )
    monkeypatch.setattr(
        rmap_routes,
        "_register_version",
        lambda **values: registered_links.append(values["expected_link"]),
    )

    http = app.test_client()
    # An older, legitimately issued link is information an attacker could
    # plausibly learn. Test its server nonce and adjacent values on a new link.
    previous_client_nonce = 0x123456789ABCDEEF
    previous_response1 = http.post(
        "/api/rmap-initiate",
        json=_wire_message(
            server_key.pubkey,
            {"identity": identity, "nonceClient": previous_client_nonce},
        ),
    )
    assert previous_response1.status_code == 200
    previous_challenge = _decrypt_wire_message(
        client_key, previous_response1.get_json()
    )
    previous_server_nonce = previous_challenge["nonceServer"]
    previous_response2 = http.post(
        "/api/rmap-get-link",
        json=_wire_message(
            server_key.pubkey, {"nonceServer": previous_server_nonce}
        ),
    )
    previous_link = f"{previous_client_nonce:016x}{previous_server_nonce:016x}"
    assert previous_response2.status_code == 200
    assert registered_links == [previous_link]

    client_nonce = 0x123456789ABCDEF0
    response1 = http.post(
        "/api/rmap-initiate",
        json=_wire_message(
            server_key.pubkey,
            {"identity": identity, "nonceClient": client_nonce},
        ),
    )
    assert response1.status_code == 200

    # Only the test harness uses the client private key. The attack messages
    # above and below are made with the server public key alone.
    challenge = _decrypt_wire_message(client_key, response1.get_json())
    assert challenge["nonceClient"] == client_nonce
    actual_server_nonce = challenge["nonceServer"]

    candidate_nonces = {
        0,
        1,
        2,
        previous_server_nonce,
        (previous_server_nonce - 1) % (1 << 64),
        (previous_server_nonce + 1) % (1 << 64),
    }
    for guessed_nonce in candidate_nonces:
        if guessed_nonce == actual_server_nonce:
            continue
        attempted_link = f"{client_nonce:016x}{guessed_nonce:016x}"
        guess_response = http.post(
            "/api/rmap-get-link",
            json=_wire_message(
                server_key.pubkey, {"nonceServer": guessed_nonce}
            ),
        )
        assert guess_response.status_code == 400
        assert registered_links == [previous_link]
        assert not (storage_dir / f"{attempted_link}.pdf").exists()

    # A correct response succeeds on the same challenge after wrong guesses.
    response2 = http.post(
        "/api/rmap-get-link",
        json=_wire_message(
            server_key.pubkey, {"nonceServer": actual_server_nonce}
        ),
    )
    expected_link = f"{client_nonce:016x}{actual_server_nonce:016x}"
    assert response2.status_code == 200
    assert _decrypt_wire_message(client_key, response2.get_json())["result"].endswith(
        expected_link
    )
    assert registered_links == [previous_link, expected_link]
    assert (storage_dir / f"{expected_link}.pdf").exists()
