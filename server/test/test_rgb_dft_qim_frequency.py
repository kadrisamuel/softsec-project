import numpy as np

from app.watermarking.rgb_dft_qim.dft_qim import (
    embed_bytes,
    extract_bytes,
)


DATA = bytes(range(53))
POSITION_KEY = bytes(range(32))
DITHER_KEY = bytes(reversed(range(32)))


def test_clean_rgb_image_roundtrip():
    random = np.random.default_rng(42)
    image = random.integers(
        32,
        224,
        size=(512, 512, 3),
        dtype=np.uint8,
    )

    watermarked = embed_bytes(
        image,
        DATA,
        POSITION_KEY,
        DITHER_KEY,
    )

    assert watermarked.shape == image.shape
    assert watermarked.dtype == np.uint8
    assert not np.array_equal(watermarked, image)

    extracted = extract_bytes(
        watermarked,
        len(DATA),
        POSITION_KEY,
        DITHER_KEY,
    )

    assert extracted == DATA