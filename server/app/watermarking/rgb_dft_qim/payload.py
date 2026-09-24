import re

from cryptography.hazmat.primitives import constant_time, hashes, hmac

_VERSION = 1
_TAG_LENGTH = 16
_SECRET_LENGTH = 16
_PAYLOAD_LENGTH = 1 + _SECRET_LENGTH + _TAG_LENGTH
_AUTH_KEY_LENGTH = 32


def encode_payload(secret: str, auth_key: bytes) -> bytes:
    _validate_auth_key(auth_key)
    if not isinstance(secret, str) or re.fullmatch(r"[0-9a-f]{32}", secret) is None:
        raise ValueError(
            "Secret must contain exactly 32 lowercase hexadecimal characters"
        )

    data = bytes([_VERSION]) + bytes.fromhex(secret)
    tag = _calculate_tag(data, auth_key)
    return data + tag


def decode_payload(payload: bytes, auth_key: bytes) -> str:
    _validate_auth_key(auth_key)
    if len(payload) != _PAYLOAD_LENGTH:
        raise ValueError(
            f"Payload must contain exactly {_PAYLOAD_LENGTH} bytes"
        )

    data = payload[:-_TAG_LENGTH]
    tag = payload[-_TAG_LENGTH:]
    expected_tag = _calculate_tag(data, auth_key)

    if not constant_time.bytes_eq(tag, expected_tag):
        raise ValueError(
            "Payload authentication failed"
        )
    
    if data[0] != _VERSION:
        raise ValueError(
            f"Unsupported payload version: {data[0]}"
        )
    
    return data[1:].hex()


def _calculate_tag(data: bytes, auth_key: bytes) -> bytes:
    hmac_context = hmac.HMAC(auth_key, hashes.SHA256())
    hmac_context.update(data)
    return hmac_context.finalize()[:_TAG_LENGTH]


def _validate_auth_key(auth_key: bytes) -> None:
    if not isinstance(auth_key, bytes) or len(auth_key) != _AUTH_KEY_LENGTH:
        raise ValueError(
            f"Authentication key must contain exactly "
            f"{_AUTH_KEY_LENGTH} bytes"
        )
