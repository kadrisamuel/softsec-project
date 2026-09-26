import pytest

from app.watermarking.rgb_dft_qim.payload import (
    decode_payload,
    encode_payload,
)

SECRET = "00112233445566778899aabbccddeeff"
AUTHENTICATION_KEY = bytes(range(32))


def test_encoded_payload_has_expected_layout():
    payload = encode_payload(SECRET, AUTHENTICATION_KEY)

    assert len(payload) == 33
    assert payload[0] == 1
    assert payload[1:17] == bytes.fromhex(SECRET)


def test_payload_roundtrip():
    payload = encode_payload(SECRET, AUTHENTICATION_KEY)

    assert decode_payload(payload, AUTHENTICATION_KEY) == SECRET


def test_decode_rejects_tampered_payload():
    # Make the payload editable
    payload = bytearray(encode_payload(SECRET, AUTHENTICATION_KEY))
    # Flip a bit in the first secret byte
    payload[1] ^= 1

    with pytest.raises(ValueError, match="authentication failed"):
        decode_payload(bytes(payload), AUTHENTICATION_KEY)


def test_decode_rejects_wrong_key():
    payload = encode_payload(SECRET, AUTHENTICATION_KEY)
    wrong_key = bytes(reversed(AUTHENTICATION_KEY))

    with pytest.raises(ValueError, match="authentication failed"):
        decode_payload(payload, wrong_key)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "0" * 31,
        "0" * 33,
        "A" * 32,
        "g" * 32,
        123,
        None,
    ],
)
def test_encode_rejects_invalid_secret(secret):
    with pytest.raises(
        ValueError,
        match="32 lowercase hexadecimal characters",
    ):
        encode_payload(secret, AUTHENTICATION_KEY)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x00" * 32,
        b"\x00" * 34,
    ],
)
def test_decode_rejects_invalid_payload_length(payload):
    with pytest.raises(ValueError, match="exactly 33 bytes"):
        decode_payload(payload, AUTHENTICATION_KEY)


@pytest.mark.parametrize(
    "auth_key",
    [
        b"",
        b"\x00" * 31,
        b"\x00" * 33,
        "not-bytes",
        None,
    ],
)
def test_encode_rejects_invalid_authentication_key(auth_key):
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        encode_payload(SECRET, auth_key)
