"""Runs any PIO program on pioemu against pin waveforms.

Inputs are waveforms on GPIOs, as (level, duration in PIO cycles) segments. The program gets the TX words it is
given up front. Every word it pushes to the RX FIFO is recorded and, by default, taken out of the FIFO right away,
like a fast CPU would. Every change of the output pins is recorded as well.

The state machine settings (wrap, pin mapping, shift configuration, ...) come from the program, see config.py.
Program specific stimulus and decoding belong to the tests, see hcs300_capture.py for an example.
"""

import bisect
from collections import deque
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import pioemu
from pioemu import State

from .programs import SmProgram

Segment = tuple[int, int]
"""(pin level, duration in PIO cycles)"""


@dataclass(frozen=True)
class Push:
    cycle: int
    """PIO cycle on which the push instruction ran"""
    word: int


@dataclass(frozen=True)
class PinChange:
    cycle: int
    """PIO cycle on which the instruction that changed the pins ran. Delay cycles come after it."""
    values: int
    """Pin values after the change, one bit per GPIO"""
    directions: int
    """Pin directions after the change, 1 = output"""


@dataclass(frozen=True)
class Trace:
    pushes: list[Push]
    pin_changes: list[PinChange]
    cycles: int
    """Length of the run in PIO cycles"""
    final: State

    def output_segments(self, pin: int, end: int | None = None) -> list[Segment]:
        """Level of an output pin over time as (level, cycles) segments. The pin is low at cycle 0 and the
        waveform runs up to `end`, by default the end of the run."""
        end = self.cycles if end is None else end
        segments: list[Segment] = []
        level, since = 0, 0
        for change in self.pin_changes:
            new_level = (change.values >> pin) & 1
            if new_level != level and change.cycle < end:
                if change.cycle > since:
                    segments.append((level, change.cycle - since))
                level, since = new_level, change.cycle
        if end > since:
            segments.append((level, end - since))
        return segments


def run(
    sm: SmProgram,
    *,
    tx_words: Sequence[int] = (),
    inputs: Mapping[int, Sequence[Segment]] | None = None,
    cycles: int | None = None,
    drain_rx: bool = True,
) -> Trace:
    """Executes `sm.program` for `cycles` PIO cycles, by default as long as the longest input waveform.

    A GPIO without a waveform reads low, a waveform ends with its last level held.
    """
    inputs = inputs or {}
    waveforms = {pin: _Waveform(segments) for pin, segments in inputs.items()}
    total = max([cycles or 0] + [waveform.total for waveform in waveforms.values()])
    if total <= 0:
        raise ValueError("nothing to run: give input waveforms or cycles")

    # pioemu looks at the real type of this annotation, so this module must not use
    # `from __future__ import annotations`
    def pins(clock: int) -> int:
        return sum(waveform.level(clock) << pin for pin, waveform in waveforms.items())

    pushes: list[Push] = []
    pin_changes: list[PinChange] = []
    state = State(transmit_fifo=deque(tx_words))
    while state.clock < total:
        generator = pioemu.emulate(
            sm.program.code,
            stop_when=lambda opcode, s: s.clock >= total or (drain_rx and len(s.receive_fifo) > 0),
            initial_state=state,
            input_source=pins,
            **sm.config.options,
        )
        last = None
        for before, after in generator:
            if len(after.receive_fifo) > len(before.receive_fifo):
                pushes.append(Push(before.clock, after.receive_fifo[-1]))
            if (after.pin_values, after.pin_directions) != (before.pin_values, before.pin_directions):
                pin_changes.append(PinChange(before.clock, after.pin_values, after.pin_directions))
            last = after
        if last is None:
            break
        state = replace(last, receive_fifo=deque()) if drain_rx else last
        if not drain_rx:
            break
    return Trace(pushes=pushes, pin_changes=pin_changes, cycles=total, final=state)


class _Waveform:
    def __init__(self, segments: Sequence[Segment]):
        self.bounds: list[int] = []
        self.levels: list[int] = []
        self.total = 0
        for level, cycles in segments:
            self.total += cycles
            self.bounds.append(self.total)
            self.levels.append(level)

    def level(self, clock: int) -> int:
        if not self.levels:
            return 0
        return self.levels[min(bisect.bisect_right(self.bounds, clock), len(self.levels) - 1)]


def to_cycles(segments_us: Sequence[tuple[int, float]], cycles_per_us: int) -> list[Segment]:
    """Waveform given as (level, duration in us) -> (level, duration in PIO cycles)"""
    return [(level, max(1, round(duration * cycles_per_us))) for level, duration in segments_us]
