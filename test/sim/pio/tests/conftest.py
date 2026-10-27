import pytest

from pio_sim.firmware import Firmware, load_firmware


@pytest.fixture(scope="session")
def fw() -> Firmware:
    """The HCS300 pulse measurement program and settings, as written in sw/kso-fw-rs/src/main.rs"""
    return load_firmware()
