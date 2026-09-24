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