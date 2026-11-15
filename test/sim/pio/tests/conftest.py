import pytest

from pio_sim.capture import Capture
from pio_sim.programs import SmProgram, load_program

# The capture program pulls this word from the TX FIFO at the start: ticks (1 tick = 1 us) of silence until a
# level counts as idle. The firmware's HCS300_TIMEOUT_TICKS has the same value, but the tests do not depend on it.
CAPTURE_TIMEOUT_TICKS = 10_000


@pytest.fixture(scope="session")
def pio_program():
    """Factory of simulated programs: `pio_program("name.pio", clock_hz=..., out_base=..., ...)`.

    Loads a file of the firmware's PIO directory (or a path) with the settings of the file and applies the
    overrides of the test on top, see `SmProgram.configured()`. The result is immutable, so every test gets
    its own configuration without affecting the others.
    """

    def make(name, **overrides) -> SmProgram:
        sm = load_program(name)
        return sm.configured(**overrides) if overrides else sm

    return make


@pytest.fixture(scope="session")
def capture(pio_program) -> Capture:
    """The HCS300 capture program, with the settings from its .pio file"""
    return Capture(pio_program("hcs300_capture.pio"), CAPTURE_TIMEOUT_TICKS)
