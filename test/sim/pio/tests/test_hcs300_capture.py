"""Behaviour of the HCS300 capture PIO program (hcs300_capture.pio), simulated on pioemu.

The PIO program pushes one word per edge, `timeout_ticks - word` is the duration of the pulse that
just ended in ticks (1 tick = 1 us). If the line stays at one level for `timeout_ticks`, it pushes
the sentinel once instead. The tests choose `timeout_ticks` (see conftest.py), it is the word the
program pulls from the TX FIFO.
"""

import random
import statistics
from dataclasses import replace

import pytest

from pio_sim.hcs300_capture import SENTINEL, Event
from pio_sim.harness import to_cycles
from pio_sim.waveforms import hcs300_frame, merge_runs

# One tick is the sampling granularity of the measurement
TOLERANCE_TICKS = 1

# HCS300 datasheet (DS21137G) table 9-4: TE is at most 660 us, the header is 10 TE
LONGEST_LEGITIMATE_PULSE_US = 10 * 660


def pulses(events: list[Event]) -> list[int]:
    return [event.ticks for event in events if event.kind == "pulse"]


def expected_events(runs: list[tuple[int, int]], timeout_ticks: int) -> list[tuple[str, int | None]]:
    """What the program has to report for a waveform made of `runs`.

    runs[0] is the idle level before the first rising edge, which is not measured. A low run longer
    than the timeout is reported as idle, every other run as a pulse of its duration.
    """
    expected: list[tuple[str, int | None]] = []
    for level, duration in runs[1:]:
        if duration > timeout_ticks:
            assert level == 0, "stuck high is covered by its own test"
            expected.append(("idle", None))
        else:
            expected.append(("pulse", duration))
    return expected


def assert_events(events: list[Event], expected: list[tuple[str, int | None]]) -> None:
    assert [event.kind for event in events] == [kind for kind, _ in expected]
    errors = [
        event.ticks - duration
        for event, (kind, duration) in zip(events, expected)
        if kind == "pulse"
    ]
    assert max(abs(error) for error in errors) <= TOLERANCE_TICKS


def test_settings_were_read_from_the_pio_file(hcs300_capture):
    assert len(hcs300_capture.sm.program.code) > 0
    assert hcs300_capture.cycles_per_us >= 1


def test_program_fits_in_pio_instruction_memory(hcs300_capture):
    assert len(hcs300_capture.sm.program.code) <= 32


def test_timeout_of_the_tests_is_longer_than_the_longest_legitimate_pulse(hcs300_capture):
    """Precondition of the frame tests. The firmware's own timeout is checked at compile time in main.rs."""
    assert hcs300_capture.timeout_ticks > LONGEST_LEGITIMATE_PULSE_US


def test_pulse_durations_are_unbiased_on_both_edges(hcs300_capture):
    """Random pulse widths at random phase against the PIO clock.

    Every cycle between an edge and the next sample has to be counted, so neither the high nor the
    low pulses may read short or long on average.
    """
    cpu = hcs300_capture.cycles_per_us
    random_generator = random.Random(1)
    segments = [(0, 20_000 * cpu)]
    widths = []
    level = 1
    for _ in range(120):
        width = random_generator.randint(150 * cpu, 3000 * cpu)
        segments.append((level, width))
        widths.append(width)
        level ^= 1
    segments.append((level, 40_000 * cpu))

    measured = pulses(hcs300_capture.simulate_cycles(segments))

    assert len(measured) == len(widths)
    errors = [ticks - width / cpu for ticks, width in zip(measured, widths)]
    high, low = errors[0::2], errors[1::2]
    assert max(abs(error) for error in errors) <= TOLERANCE_TICKS
    assert abs(statistics.fmean(high)) <= 0.2
    assert abs(statistics.fmean(low)) <= 0.2
    assert abs(statistics.fmean(high) - statistics.fmean(low)) <= 0.2


def test_short_pulses_are_all_reported(hcs300_capture):
    """20 us is far below the shortest TE (65 us), the edge handlers must not lose such pulses"""
    segments = [(0, 2_000)] + [(1 - i % 2, 20) for i in range(40)] + [(0, 60_000)]

    events = hcs300_capture.simulate(segments)

    assert_events(events, [("pulse", 20)] * 39 + [("idle", None)])


@pytest.mark.parametrize("te_us", [65, 100, 400, 660])
def test_hcs300_frame_is_measured_pulse_by_pulse(hcs300_capture, te_us):
    """A whole code word (155 measurable pulses) at the extremes of the TE range"""
    frame = hcs300_frame(te_us, trailing_idle_us=15_000)
    runs = [(0, 12_000)] + frame

    events = hcs300_capture.simulate(runs)

    expected = expected_events(runs, hcs300_capture.timeout_ticks)
    assert [kind for kind, _ in expected] == ["pulse"] * 155 + ["idle"]
    assert_events(events, expected)


@pytest.mark.parametrize(
    "te_us, guard_ends_word",
    [
        (400, True),  # guard time 39 TE = 15.6 ms is longer than the timeout: idle between words
        (100, False),  # 3.9 ms is shorter: the words run into each other, no idle marker
    ],
)
def test_back_to_back_code_words(hcs300_capture, te_us, guard_ends_word):
    frame = hcs300_frame(te_us)
    runs = merge_runs([(0, 12_000)] + frame + frame + [(0, 15_000)])

    events = hcs300_capture.simulate(runs)

    expected = expected_events(runs, hcs300_capture.timeout_ticks)
    idles = [kind for kind, _ in expected].count("idle")
    assert idles == (2 if guard_ends_word else 1)
    assert_events(events, expected)


@pytest.mark.parametrize("timeout_ticks", [3_000, 10_000])
def test_idle_timeout_pushes_a_single_sentinel(hcs300_capture, timeout_ticks):
    """The timeout is just the word pulled from the TX FIFO, the program works with any value"""
    hcs300_capture = replace(hcs300_capture, timeout_ticks=timeout_ticks)
    lead_us, pulse_us, idle_us = 5_000, 500, 3 * timeout_ticks + 10_000

    pushes = hcs300_capture.pushes(to_cycles([(0, lead_us), (1, pulse_us), (0, idle_us)], hcs300_capture.cycles_per_us))
    events = hcs300_capture.interpret(pushes)

    assert [event.kind for event in events] == ["pulse", "idle"]
    assert pushes[1].word == SENTINEL  # the counter underflowed
    assert abs(events[0].ticks - pulse_us) <= TOLERANCE_TICKS
    falling_edge = (lead_us + pulse_us) * hcs300_capture.cycles_per_us
    idle_after_us = (events[1].cycle - falling_edge) / hcs300_capture.cycles_per_us
    assert timeout_ticks <= idle_after_us <= timeout_ticks + 2


def test_stuck_high_pushes_sentinel_and_measurement_resumes(hcs300_capture):
    stuck_us = hcs300_capture.timeout_ticks + 2_000
    segments = [
        (0, 5_000),
        (1, 2_000),
        (0, 1_000),
        (1, stuck_us),  # line stuck high past the timeout
        (0, 3_000),
        (1, 400),
        (0, 400),
        (1, 400),
        (0, 60_000),
    ]

    events = hcs300_capture.simulate(segments)

    assert_events(
        events,
        [("pulse", 2_000), ("pulse", 1_000), ("idle", None)]
        + [("pulse", 400)] * 3
        + [("idle", None)],
    )
