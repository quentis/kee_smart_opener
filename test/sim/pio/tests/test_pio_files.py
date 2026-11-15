"""Every PIO file of the firmware has to be loadable by the simulation: assemble and state machine settings.

A file does not need a clock: for a program whose speed is up to the user (a PIO SPI, say) the tests choose it.
"""

import pytest

from pio_sim.programs import PIO_DIR, load_program, pio_files


def test_pio_files_were_found():
    assert pio_files(), f"no .pio files in {PIO_DIR}"


@pytest.mark.parametrize("path", pio_files(), ids=lambda path: path.name)
def test_pio_file_loads(path):
    sm = load_program(path)

    assert len(sm.program.code) <= 32, "does not fit in the instruction memory"


def test_capture_program_settings():
    sm = load_program("hcs300_capture.pio")

    assert sm.config.pio_hz == 5_000_000
    assert sm.cycles_per_us == 5
    assert sm.config.options["in_base"] == sm.config.options["jmp_pin"] == 0
