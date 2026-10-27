"""Behaviour of the firmware's HCS300 capture PIO program, simulated on pioemu.

The PIO program pushes one word per edge, `timeout_ticks - word` is the duration of the pulse that
just ended in ticks (1 tick = 1 us). If the line stays at one level for `timeout_ticks`, it pushes
the sentinel once instead.
"""

import random
import statistics

import pytest

from pio_sim.harness import Event, simulate, simulate_cycles
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


def test_firmware_settings_were_read(fw):
    assert len(fw.program.code) > 0
    assert fw.timeout_ticks > 0
    assert fw.cycles_per_us >= 1


def test_program_fits_in_pio_instruction_memory(fw):
    assert len(fw.program.code) <= 32


def test_timeout_is_longer_than_the_longest_legitimate_pulse(fw):
    assert fw.timeout_ticks > LONGEST_LEGITIMATE_PULSE_US


def test_pulse_durations_are_unbiased_on_both_edges(fw):
    """Random pulse widths at random phase against the PIO clock.

    Every cycle between an edge and the next sample has to be counted, so neither the high nor the
    low pulses may read short or long on average.
    """
    cpu = fw.cycles_per_us
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

    measured = pulses(simulate_cycles(fw, segments))

    assert len(measured) == len(widths)
    errors = [ticks - width / cpu for ticks, width in zip(measured, widths)]
    high, low = errors[0::2], errors[1::2]
    assert max(abs(error) for error in errors) <= TOLERANCE_TICKS
    assert abs(statistics.fmean(high)) <= 0.2
    assert abs(statistics.fmean(low)) <= 0.2
    assert abs(statistics.fmean(high) - statistics.fmean(low)) <= 0.2


def test_short_pulses_are_all_reported(fw):
    """20 us is far below the shortest TE (65 us), the edge handlers must not lose such pulses"""
    segments = [(0, 2_000)] + [(1 - i % 2, 20) for i in range(40)] + [(0, 60_000)]

    events = simulate(fw, segments)

    assert_events(events, [("pulse", 20)] * 39 + [("idle", None)])


@pytest.mark.parametrize("te_us", [65, 100, 400, 660])
def test_hcs300_frame_is_measured_pulse_by_pulse(fw, te_us):
    """A whole code word (155 measurable pulses) at the extremes of the TE range"""
    frame = hcs300_frame(te_us, trailing_idle_us=15_000)
    runs = [(0, 12_000)] + frame

    events = simulate(fw, runs)

    expected = expected_events(runs, fw.timeout_ticks)
    assert [kind for kind, _ in expected] == ["pulse"] * 155 + ["idle"]
    assert_events(events, expected)


@pytest.mark.parametrize(
    "te_us, guard_ends_word",
    [
        (400, True),  # guard time 39 TE = 15.6 ms is longer than the timeout: idle between words
        (100, False),  # 3.9 ms is shorter: the words run into each other, no idle marker
    ],
)
def test_back_to_back_code_words(fw, te_us, guard_ends_word):
    frame = hcs300_frame(te_us)
    runs = merge_runs([(0, 12_000)] + frame + frame + [(0, 15_000)])

    events = simulate(fw, runs)

    expected = expected_events(runs, fw.timeout_ticks)
    idles = [kind for kind, _ in expected].count("idle")
    assert idles == (2 if guard_ends_word else 1)
    assert_events(events, expected)


def test_idle_timeout_pushes_a_single_sentinel(fw):
    lead_us, pulse_us, idle_us = 5_000, 500, 80_000

    events = simulate(fw, [(0, lead_us), (1, pulse_us), (0, idle_us)])

    assert [event.kind for event in events] == ["pulse", "idle"]
    assert abs(events[0].ticks - pulse_us) <= TOLERANCE_TICKS
    falling_edge = (lead_us + pulse_us) * fw.cycles_per_us
    idle_after_us = (events[1].cycle - falling_edge) / fw.cycles_per_us
    assert fw.timeout_ticks <= idle_after_us <= fw.timeout_ticks + 2


def test_stuck_high_pushes_sentinel_and_measurement_resumes(fw):
    stuck_us = fw.timeout_ticks + 2_000
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

    events = simulate(fw, segments)

    assert_events(
        events,
        [("pulse", 2_000), ("pulse", 1_000), ("idle", None)]
        + [("pulse", 400)] * 3
        + [("idle", None)],
    )
