from .key_schedule import derive_keys
from .payload import decode_payload, encode_payload


def encode_message(secret: str, master_key: str) -> bytes:
    keys = derive_keys(master_key)
    return encode_payload(secret, keys.authentication)


def decode_message(message: bytes, master_key: str) -> str:
    keys = derive_keys(master_key)
    return decode_payload(message, keys.authentication)


__all__ = ["decode_message", "encode_message"]