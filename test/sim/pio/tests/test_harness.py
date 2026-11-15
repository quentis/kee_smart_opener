"""The generic runner: any program, pin mapping from the program's settings, TX words in, pushes and pins out."""

import pytest

from pio_sim.harness import run
from pio_sim.programs import from_source


def test_output_pin_waveform_follows_the_settings_of_the_program():
    sm = from_source(
        """
.lang_opt sim set_base = 2
.lang_opt sim set_count = 1
.wrap_target
    set pins, 1 [3]
    set pins, 0 [1]
.wrap
"""
    )

    trace = run(sm, cycles=24)

    assert trace.output_segments(2) == [(1, 4), (0, 2)] * 4
    assert trace.output_segments(0) == [(0, 24)]  # pin 0 is not touched
    assert {change.values for change in trace.pin_changes} == {0b100, 0}


def test_waveform_ends_at_the_requested_cycle():
    sm = from_source(".lang_opt sim set_count = 1\n.wrap_target\nset pins, 1 [3]\nset pins, 0 [1]\n.wrap")

    trace = run(sm, cycles=10)

    assert trace.output_segments(0) == [(1, 4), (0, 2), (1, 4)]
    assert trace.output_segments(0, end=5) == [(1, 4), (0, 1)]


def test_input_pin_is_relative_to_in_base():
    sm = from_source(".lang_opt sim in_base = 3\n.wrap_target\n    in pins, 1\n    push noblock\n.wrap")

    on_gpio_3 = run(sm, inputs={3: [(0, 10), (1, 10)]})
    on_gpio_0 = run(sm, inputs={0: [(1, 20)]})

    words = [push.word for push in on_gpio_3.pushes]
    assert words[0] == 0
    assert words[-1] == 0x8000_0000  # a single 1 shifted in from the left
    assert {push.word for push in on_gpio_0.pushes} == {0}


def test_tx_words_reach_the_program():
    sm = from_source("pull\nout x, 32\nin x, 32\npush")

    trace = run(sm, tx_words=[0xDEAD_BEEF, 0x1234_5678], cycles=30)

    assert [push.word for push in trace.pushes] == [0xDEAD_BEEF, 0x1234_5678]


def test_without_draining_the_rx_fifo_fills_up():
    sm = from_source("in null, 32\npush noblock")

    drained = run(sm, cycles=40)
    filling = run(sm, cycles=40, drain_rx=False)

    assert len(drained.pushes) == 20
    assert len(filling.pushes) < len(drained.pushes)


def test_nothing_to_run_is_an_error():
    with pytest.raises(ValueError):
        run(from_source("nop"))


def test_configured_program_runs_with_the_pins_of_the_test():
    sm = from_source(".lang_opt sim set_count = 1\n.wrap_target\nset pins, 1 [3]\nset pins, 0 [1]\n.wrap")

    on_gpio_6 = run(sm.configured(set_base=6), cycles=6)
    on_gpio_0 = run(sm, cycles=6)

    assert on_gpio_6.output_segments(6) == [(1, 4), (0, 2)]
    assert on_gpio_6.output_segments(0) == [(0, 6)]
    assert on_gpio_0.output_segments(0) == [(1, 4), (0, 2)]  # the original keeps its settings
