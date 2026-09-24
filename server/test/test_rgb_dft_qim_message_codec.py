import pytest

from app.watermarking.rgb_dft_qim.message_codec import (
    decode_message,
    encode_message,
)


SECRET = "00112233445566778899aabbccddeeff"
MASTER_KEY = "example-master-key"


def test_message_roundtrip():
    message = encode_message(SECRET, MASTER_KEY)

    assert decode_message(message, MASTER_KEY) == SECRET


def test_decode_message_rejects_wrong_master_key():
    message = encode_message(SECRET, MASTER_KEY)

    with pytest.raises(ValueError, match="authentication failed"):
        decode_message(message, "different-master-key")


def test_encoded_message_contains_error_correction():
    message = encode_message(SECRET, MASTER_KEY)

    assert len(message) == 53


def test_message_recovers_from_ten_corrupted_bytes():
    message = bytearray(encode_message(SECRET, MASTER_KEY))

    for index in range(10):
        message[index] ^= 1

    assert decode_message(bytes(message), MASTER_KEY) == SECRET


def test_message_rejects_eleven_corrupted_bytes():
    message = bytearray(encode_message(SECRET, MASTER_KEY))

    for index in range(11):
        message[index] ^= 1

    with pytest.raises(ValueError):
        decode_message(bytes(message), MASTER_KEY)
