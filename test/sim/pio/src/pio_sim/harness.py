"""Runs the firmware's PIO program on pioemu against a pin waveform.

The state machine sees the waveform on GPIO 0 (used for both `wait pin 0` and `jmp pin`), gets
`timeout_ticks` in its TX FIFO, and its RX FIFO is emptied after every push, like a fast CPU would.
"""

import bisect
from collections import deque
from dataclasses import dataclass, replace
from typing import Literal, Sequence

import pioemu
from pioemu import State

from .assembler import Program
from .firmware import Firmware

Segment = tuple[int, int]
"""(pin level, duration in PIO cycles)"""


@dataclass(frozen=True)
class Push:
    cycle: int
    """PIO cycle on which the push instruction ran"""
    word: int


@dataclass(frozen=True)
class Event:
    """One RX FIFO word, interpreted the way the Rust side does."""

    kind: Literal["pulse", "idle"]
    cycle: int
    ticks: int
    """Pulse duration in ticks (1 tick = 1 us), 0 for idle"""


def run_program(program: Program, segments: Sequence[Segment], tx_words: Sequence[int]) -> list[Push]:
    """Executes `program` for the whole waveform and returns every word it pushed."""
    bounds: list[int] = []
    levels: list[int] = []
    total = 0
    for level, cycles in segments:
        total += cycles
        bounds.append(total)
        levels.append(level)

    # pioemu looks at the real type of this annotation, so this module must not use
    # `from __future__ import annotations`
    def pins(clock: int) -> int:
        return levels[min(bisect.bisect_right(bounds, clock), len(levels) - 1)]

    pushes: list[Push] = []
    state = State(transmit_fifo=deque(tx_words))
    while state.clock < total:
        generator = pioemu.emulate(
            program.code,
            stop_when=lambda opcode, s: s.clock >= total or len(s.receive_fifo) > 0,
            initial_state=state,
            input_source=pins,
            jmp_pin=0,
            wrap_target=program.wrap_target,
            wrap_top=program.wrap_top,
        )
        last = None
        for before, after in generator:
            if len(after.receive_fifo) > len(before.receive_fifo):
                pushes.append(Push(before.clock, after.receive_fifo[-1]))
            last = after
        if last is None:
            break
        state = replace(last, receive_fifo=deque())
    return pushes


def interpret(firmware: Firmware, pushes: Sequence[Push]) -> list[Event]:
    """Same decoding as the firmware task: sentinel = idle, otherwise duration = T - word."""
    events = []
    for push in pushes:
        if push.word == firmware.sentinel:
            events.append(Event("idle", push.cycle, 0))
        else:
            events.append(Event("pulse", push.cycle, firmware.timeout_ticks - push.word))
    return events


def simulate_cycles(firmware: Firmware, segments: Sequence[Segment]) -> list[Event]:
    pushes = run_program(firmware.program, segments, [firmware.timeout_ticks])
    return interpret(firmware, pushes)


def simulate(firmware: Firmware, segments_us: Sequence[tuple[int, float]]) -> list[Event]:
    """Like simulate_cycles(), with the waveform given as (level, duration in us)."""
    return simulate_cycles(firmware, to_cycles(segments_us, firmware.cycles_per_us))


def to_cycles(segments_us: Sequence[tuple[int, float]], cycles_per_us: int) -> list[Segment]:
    return [(level, max(1, round(duration * cycles_per_us))) for level, duration in segments_us]
