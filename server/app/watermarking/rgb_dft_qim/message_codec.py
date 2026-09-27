"""Encode and decode watermark secrets with authentication, error correction, and byte interleaving."""

from reedsolo import ReedSolomonError, RSCodec

from .key_schedule import derive_keys
from .payload import decode_payload, encode_payload
from .interleaving import deinterleave_bytes, interleave_bytes

_PARITY_BYTES = 20
_RS_CODEC = RSCodec(_PARITY_BYTES)

ENCODED_MESSAGE_BYTES = 53


def encode_message(secret: str, master_key: str) -> bytes:
    """Authenticate the secret, add error correction, and shuffle (interleave) the resulting bytes."""
    keys = derive_keys(master_key)
    payload = encode_payload(secret, keys.authentication)
    corrected = bytes(_RS_CODEC.encode(payload))
    return interleave_bytes(corrected, keys.interleaving)


def decode_message(message: bytes, master_key: str) -> str:
    """Undo interleaving, correct errors, and verify the secret's HMAC, return the secret."""
    keys = derive_keys(master_key)
    deinterleaved = deinterleave_bytes(
        message,
        keys.interleaving,
    )

    try:
        decoded_payload = bytes(
            _RS_CODEC.decode(deinterleaved)[0]
        )
    except ReedSolomonError as exc:
        raise ValueError("Message error correction failed") from exc

    return decode_payload(decoded_payload, keys.authentication)


__all__ = ["decode_message", "encode_message", "ENCODED_MESSAGE_BYTES"]
