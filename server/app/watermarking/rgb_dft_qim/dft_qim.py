import hmac

import numpy as np


_QUANTIZATION_STEP = 16_000.0
_MIN_FREQUENCY_RADIUS = 20.0
_MAX_FREQUENCY_RADIUS = 100.0


def embed_bytes(
    image: np.ndarray,
    data: bytes,
    position_key: bytes,
    dither_key: bytes,
) -> np.ndarray:
    # np.unpackbits converts 53 bytes into 424 bits.
    # Extraction gets three decisions per bit—one from
    # each RGB channel—and accepts a bit as 1 when at
    # least two channels vote for it.
    bits = np.unpackbits(
        np.frombuffer(data, dtype=np.uint8)
    )

    pairs = _coefficient_pairs(
        image.shape[0],
        image.shape[1],
        len(bits),
        position_key,
    )

    watermarked = np.empty_like(image)

    for channel_index in range(3):
        watermarked[:, :, channel_index] = _embed_channel(
            image[:, :, channel_index],
            bits,
            pairs,
            dither_key,
        )

    return watermarked


def extract_bytes(
    image: np.ndarray,
    byte_count: int,
    position_key: bytes,
    dither_key: bytes,
) -> bytes:
    bit_count = byte_count * 8

    pairs = _coefficient_pairs(
        image.shape[0],
        image.shape[1],
        bit_count,
        position_key,
    )

    channel_results = np.stack(
        [
            _extract_channel(
                image[:, :, channel_index],
                bit_count,
                pairs,
                dither_key,
            )
            for channel_index in range(3)
        ]
    )

    majority_bits = (
        channel_results.sum(axis=0) >= 2
    ).astype(np.uint8)

    return np.packbits(majority_bits).tobytes()


def _keyed_value(key: bytes, label: bytes) -> bytes:
    return hmac.digest(key, label, "sha256")


def _dither(index: int, key: bytes) -> float:
    """Return a key-derived QIM grid offset for one bit."""

    label = b"dither:" + index.to_bytes(4, byteorder="big")
    value = int.from_bytes(_keyed_value(key, label)[:8], "big")
    fraction = value / (1 << 64)
    return fraction * _QUANTIZATION_STEP


def _coefficient_pairs(
    height: int,
    width: int,
    count: int,
    key: bytes,
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Select two keyed low-to-mid-frequency coefficients for every embedded bit."""
    candidates = []

    for row in range(height):
        vertical_frequency = min(row, height - row)

        for column in range(1, width // 2):
            radius = np.hypot(vertical_frequency, column)

            if (
                _MIN_FREQUENCY_RADIUS
                <= radius
                <= _MAX_FREQUENCY_RADIUS
            ):
                candidates.append((row, column))

    required = count * 2
    if len(candidates) < required:
        raise ValueError("Image is too small for the message")

    def sort_value(position: tuple[int, int]) -> bytes:
        row, column = position
        label = (
            b"position:"
            + row.to_bytes(4, "big")
            + column.to_bytes(4, "big")
        )
        return _keyed_value(key, label)

    candidates.sort(key=sort_value)
    selected = candidates[:required]

    return [
        (selected[index], selected[index + 1])
        for index in range(0, required, 2)
    ]


def _embed_channel(
    channel: np.ndarray,
    bits: np.ndarray,
    pairs: list[tuple[tuple[int, int], tuple[int, int]]],
    dither_key: bytes,
) -> np.ndarray:
    spectrum = np.fft.rfft2(channel.astype(np.float64))

    for index, bit in enumerate(bits):
        first, second = pairs[index]
        first_value = spectrum[first]
        second_value = spectrum[second]

        first_magnitude = abs(first_value)
        second_magnitude = abs(second_value)
        difference = first_magnitude - second_magnitude

        offset = (
            _dither(index, dither_key)
            + int(bit) * _QUANTIZATION_STEP / 2
        )
        target = (
            _QUANTIZATION_STEP
            * round(
                (difference - offset)
                / _QUANTIZATION_STEP
            )
            + offset
        )

        average = max(
            (first_magnitude + second_magnitude) / 2,
            abs(target) / 2,
        )

        spectrum[first] = (
            average + target / 2
        ) * np.exp(1j * np.angle(first_value))

        spectrum[second] = (
            average - target / 2
        ) * np.exp(1j * np.angle(second_value))

    reconstructed = np.fft.irfft2(
        spectrum,
        s=channel.shape,
    )

    return np.rint(
        np.clip(reconstructed, 0, 255)
    ).astype(np.uint8)


def _extract_channel(
    channel: np.ndarray,
    bit_count: int,
    pairs: list[tuple[tuple[int, int], tuple[int, int]]],
    dither_key: bytes,
) -> np.ndarray:
    """Extract bits from one colour channel."""
    #Repeat the same grid construction as used during embedding,
    #then choose the closer grid for every coefficient pair.

    spectrum = np.fft.rfft2(channel.astype(np.float64))
    bits = np.empty(bit_count, dtype=np.uint8)

    for index in range(bit_count):
        first, second = pairs[index]

        difference = (
            abs(spectrum[first])
            - abs(spectrum[second])
        )

        zero_offset = _dither(index, dither_key)
        one_offset = (
            zero_offset + _QUANTIZATION_STEP / 2
        )

        nearest_zero = (
            _QUANTIZATION_STEP
            * round(
                (difference - zero_offset)
                / _QUANTIZATION_STEP
            )
            + zero_offset
        )
        nearest_one = (
            _QUANTIZATION_STEP
            * round(
                (difference - one_offset)
                / _QUANTIZATION_STEP
            )
            + one_offset
        )

        zero_distance = abs(difference - nearest_zero)
        one_distance = abs(difference - nearest_one)

        bits[index] = int(one_distance < zero_distance)

    return bits


__all__ = ["embed_bytes", "extract_bytes"]
