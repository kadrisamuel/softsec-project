import numpy as np

from app.watermarking.rgb_dft_qim.key_schedule import derive_keys
from app.watermarking.rgb_dft_qim.visible import (
    add_visible_pattern,
    visible_identifier,
)


SECRET = "00112233445566778899aabbccddeeff"


def test_visible_identifier_is_deterministic():
    key = derive_keys(
        "example-master-key"
    ).visible_placement

    first = visible_identifier(SECRET, key)
    second = visible_identifier(SECRET, key)

    assert first == second
    assert first.startswith("TATOU-")
    assert len(first) == 22


def test_visible_identifier_does_not_expose_secret():
    key = derive_keys(
        "example-master-key"
    ).visible_placement

    identifier = visible_identifier(SECRET, key)

    assert SECRET not in identifier.lower()


def test_visible_pattern_is_deterministic_and_non_mutating():
    image = np.full(
        (1024, 1024, 3),
        255,
        dtype=np.uint8,
    )
    original = image.copy()
    key = derive_keys(
        "example-master-key"
    ).visible_placement

    first = add_visible_pattern(
        image,
        "TATOU-0123456789ABCDEF",
        key,
    )
    second = add_visible_pattern(
        image,
        "TATOU-0123456789ABCDEF",
        key,
    )

    assert np.array_equal(image, original)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, image)


def test_visible_pattern_repeats_across_image():
    image = np.full(
        (1024, 1024, 3),
        255,
        dtype=np.uint8,
    )
    key = derive_keys(
        "example-master-key"
    ).visible_placement

    result = add_visible_pattern(
        image,
        "TATOU-0123456789ABCDEF",
        key,
    )
    changed = np.any(result != image, axis=2)

    for row_start in (0, 512):
        for column_start in (0, 512):
            quadrant = changed[
                row_start:row_start + 512,
                column_start:column_start + 512,
            ]
            assert quadrant.any()
            