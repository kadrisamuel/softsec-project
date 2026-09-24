from reedsolo import ReedSolomonError, RSCodec

from .key_schedule import derive_keys
from .payload import decode_payload, encode_payload

_PARITY_BYTES = 20
_RS_CODEC = RSCodec(_PARITY_BYTES)


def encode_message(secret: str, master_key: str) -> bytes:
    keys = derive_keys(master_key)
    payload = encode_payload(secret, keys.authentication)
    return bytes(_RS_CODEC.encode(payload))


def decode_message(message: bytes, master_key: str) -> str:
    keys = derive_keys(master_key)

    try:
        decoded_payload = bytes(_RS_CODEC.decode(message)[0])
    except ReedSolomonError as exc:
        raise ValueError("Message error correction failed") from exc

    return decode_payload(decoded_payload, keys.authentication)


__all__ = ["decode_message", "encode_message"]
