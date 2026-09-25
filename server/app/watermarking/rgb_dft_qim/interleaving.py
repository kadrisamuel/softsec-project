"""
Purpose - Keyed Scrambling:
* Hide which image locations contain the secret, HMAC, or parity bytes.
* Make targeted removal harder without the key.
* Break up the predictable structure of the encoded message.
"""

import hmac


def interleave_bytes(data: bytes, key: bytes) -> bytes:
    permutation = _permutation(len(data), key)
    return bytes(data[index] for index in permutation)


def deinterleave_bytes(data: bytes, key: bytes) -> bytes:
    permutation = _permutation(len(data), key)
    restored = bytearray(len(data))

    for interleaved_index, original_index in enumerate(permutation):
        restored[original_index] = data[interleaved_index]

    return bytes(restored)


def _permutation(length: int, key: bytes) -> list[int]:
    """Assign each byte position a deterministic, key-dependent sorting value."""
    def sort_value(index: int) -> bytes:
        position = index.to_bytes(4, byteorder="big")
        return hmac.digest(key, b"interleave:" + position, "sha256")

    return sorted(range(length), key=sort_value)


__all__ = ["deinterleave_bytes", "interleave_bytes"]
