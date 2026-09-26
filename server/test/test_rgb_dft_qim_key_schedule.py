import pytest

from app.watermarking.rgb_dft_qim.key_schedule import derive_keys


def _key_values(keys):
    return (
        keys.authentication,
        keys.interleaving,
        keys.pilot,
        keys.qim_positions,
        keys.qim_dither,
        keys.visible_placement,
    )


def test_key_derivation_is_deterministic():
    first = derive_keys("example-master-key")
    second = derive_keys("example-master-key")

    assert first == second


def test_different_master_keys_produce_different_subkeys():
    first = _key_values(derive_keys("first-master-key"))
    second = _key_values(derive_keys("second-master-key"))

    assert all(
        first_key != second_key
        for first_key, second_key in zip(first, second)
    )


def test_component_subkeys_are_distinct():
    values = _key_values(derive_keys("example-master-key"))

    assert len(set(values)) == len(values)


def test_component_subkeys_are_256_bits():
    values = _key_values(derive_keys("example-master-key"))

    assert all(len(value) == 32 for value in values)


@pytest.mark.parametrize("master_key", ["", 123, None])
def test_invalid_master_key_is_rejected(master_key):
    with pytest.raises(ValueError, match="non-empty string"):
        derive_keys(master_key)
