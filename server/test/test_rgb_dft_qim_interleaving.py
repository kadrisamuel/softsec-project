from app.watermarking.rgb_dft_qim.interleaving import (
    deinterleave_bytes,
    interleave_bytes,
)


DATA = bytes(range(53))
KEY = bytes(range(32))


def test_byte_interleaving_roundtrip():
    interleaved = interleave_bytes(DATA, KEY)

    assert interleaved != DATA
    assert deinterleave_bytes(interleaved, KEY) == DATA