"""The `pio_program` fixture: a file of the firmware with the settings of the test on top"""

import pytest

from pio_sim.config import ConfigError


def test_without_overrides_the_settings_are_the_ones_of_the_file(pio_program):
    sm = pio_program("hcs300_capture.pio")

    assert sm.cycles_per_us == 5
    assert sm.config.options["jmp_pin"] == 0


def test_overrides_apply_to_that_program_only(pio_program):
    fast = pio_program("hcs300_capture.pio", clock_hz=10_000_000, in_base=4, jmp_pin=4)

    assert fast.cycles_per_us == 10
    assert fast.config.options["in_base"] == fast.config.options["jmp_pin"] == 4
    assert pio_program("hcs300_capture.pio").cycles_per_us == 5


@pytest.mark.parametrize("clock_hz", [1_000_000, 4_000_000, 20_000_000])
def test_the_clock_can_be_parametrized(pio_program, clock_hz):
    assert pio_program("hcs300_capture.pio", clock_hz=clock_hz).cycles_per_us == clock_hz // 1_000_000


def test_a_program_with_a_clock_divider_gets_its_clock_from_the_base_clock(pio_program):
    sm = pio_program("hcs300_capture.pio", clock_div=30)

    assert sm.config.pio_hz == sm.config.sys_clock_hz / 30


def test_bad_overrides_fail_at_load(pio_program):
    with pytest.raises(ConfigError):
        pio_program("hcs300_capture.pio", nonsense=1)
