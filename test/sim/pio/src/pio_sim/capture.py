"""Stimulus and decoding of the HCS300 capture program (`hcs300_capture.pio`).

The program pushes one word per edge: `timeout_ticks - word` is the duration of the pulse that just ended in ticks
(1 tick = 1 us). If the line stays at one level for `timeout_ticks`, it pushes the sentinel `0xFFFF_FFFF` instead
(the counter underflowed). `timeout_ticks` is what the program pulls from the TX FIFO once at the start, the tests
choose it, the firmware's value (`HCS300_TIMEOUT_TICKS`) is one of the possible ones.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .harness import Push, Segment, run, to_cycles
from .programs import SmProgram

SENTINEL = 0xFFFF_FFFF


@dataclass(frozen=True)
class Event:
    """One RX FIFO word, interpreted the way the Rust side does."""

    kind: Literal["pulse", "idle"]
    cycle: int
    ticks: int
    """Pulse duration in ticks (1 tick = 1 us), 0 for idle"""


@dataclass(frozen=True)
class Capture:
    sm: SmProgram
    timeout_ticks: int

    def __post_init__(self):
        options = self.sm.config.options
        if options.get("in_base", 0) != options.get("jmp_pin", 0):
            raise ValueError("the capture program reads one pin with both `wait pin` and `jmp pin`")

    @property
    def cycles_per_us(self) -> int:
        return self.sm.cycles_per_us

    @property
    def pin(self) -> int:
        """GPIO the waveform is applied to"""
        return self.sm.config.options.get("jmp_pin", 0)

    def pushes(self, segments: Sequence[Segment]) -> list[Push]:
        """Every word the program pushes for a waveform given in PIO cycles"""
        return run(self.sm, tx_words=[self.timeout_ticks], inputs={self.pin: segments}).pushes

    def interpret(self, pushes: Sequence[Push]) -> list[Event]:
        """Same decoding as the firmware task: sentinel = idle, otherwise duration = T - word."""
        return [
            Event("idle", push.cycle, 0)
            if push.word == SENTINEL
            else Event("pulse", push.cycle, self.timeout_ticks - push.word)
            for push in pushes
        ]

    def simulate_cycles(self, segments: Sequence[Segment]) -> list[Event]:
        return self.interpret(self.pushes(segments))

    def simulate(self, segments_us: Sequence[tuple[int, float]]) -> list[Event]:
        """Like simulate_cycles(), with the waveform given as (level, duration in us)."""
        return self.simulate_cycles(to_cycles(segments_us, self.cycles_per_us))
