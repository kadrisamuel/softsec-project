from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


_KEY_LENGTH: Final[int] = 32
_SALT: Final[bytes] = b"tatou:rgb-dft-qim:v1"


@dataclass(frozen=True)
class WatermarkKeys:
    """Independent keys used by the watermarking components."""

    authentication: bytes
    interleaving: bytes
    pilot: bytes
    qim_positions: bytes
    qim_dither: bytes
    visible_placement: bytes


def derive_keys(master_key: str) -> WatermarkKeys:
    """Derive independent 256-bit subkeys from one master key."""

    if not isinstance(master_key, str) or not master_key:
        raise ValueError("Master key must be a non-empty string")

    master_key_bytes = master_key.encode("utf-8")

    return WatermarkKeys(
        authentication=_derive_subkey(
            master_key_bytes,
            b"authentication",
        ),
        interleaving=_derive_subkey(
            master_key_bytes,
            b"interleaving",
        ),
        pilot=_derive_subkey(
            master_key_bytes,
            b"pilot",
        ),
        qim_positions=_derive_subkey(
            master_key_bytes,
            b"qim-positions",
        ),
        qim_dither=_derive_subkey(
            master_key_bytes,
            b"qim-dither",
        ),
        visible_placement=_derive_subkey(
            master_key_bytes,
            b"visible-placement",
        ),
    )


def _derive_subkey(master_key: bytes, label: bytes) -> bytes:
    """Derive one component-specific key."""

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=_SALT,
        info=b"tatou:rgb-dft-qim:v1:" + label,
    )
    return hkdf.derive(master_key)


__all__ = ["WatermarkKeys", "derive_keys"]