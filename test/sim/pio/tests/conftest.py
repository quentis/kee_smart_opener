import pytest

from pio_sim.firmware import Firmware, load_firmware


@pytest.fixture(scope="session")
def fw() -> Firmware:
    """The HCS300 capture program and its settings, as in sw/kso-fw-rs/src/main.rs and pio/"""
    return load_firmware()
