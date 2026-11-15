"""Stimulus and expected waveform of the HCS300 transmitter program (`hcs300_tx.pio`).

The program takes the 66 data bits of a code word as three TX FIFO words, shifted out LSB first, and drives the
whole frame on one pin: preamble, header, the PWM coded bits and the guard time. One TE is two PIO cycles. The
expected waveform comes from `test/system/hcs300_wf_gen.py`, the generator that drives the hardware test, so
simulation and bench agree on what a frame looks like.

The time unit of everything here is the PIO cycle. The clock only turns cycles into time, see `Hcs300Tx.te_us`.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .harness import Segment, Trace, run
from .programs import SmProgram
from .waveforms import Button, hcs300_bits, hcs300_frame, merge_runs

TE_CYCLES = 2
"""PIO cycles per TE"""

FRAME_TE = 270
"""Preamble 23 + header 10 + 66 bits * 3 + guard 39, in TE"""

FRAME_SETUP_CYCLES = 5
"""Low cycles between the end of the guard time and the first preamble pulse: `mov x, ~status`, `jmp !x`,
`set x, 11 side 0` and `nop side 0 [1]`. They make the guard time between two frames 41.5 TE long."""


@dataclass(frozen=True)
class Hcs300Codeword:
    encrypted: int = 0xA5C3_1E96
    serial: int = 0x0ABC_DEF1
    buttons: Button = Button.S1 | Button.S3
    """The pressed buttons. A plain int is accepted and converted, a value outside S0..S3 raises ValueError."""
    vlow: bool = False
    repeat: bool = True

    def __post_init__(self):
        object.__setattr__(self, "buttons", Button(self.buttons))
        object.__setattr__(self, "vlow", bool(self.vlow))
        object.__setattr__(self, "repeat", bool(self.repeat))

    @property
    def button(self) -> int:
        """The 4-bit button status field as it is transmitted (and as the Rust `Hcs300ButtonStatus` holds it):
        S3, S0, S1, S2 from bit 0 to bit 3"""
        return int(self.buttons)

    def fields(self) -> dict[str, int]:
        """The arguments of the generator, which numbers the buttons differently (bit i is S<i>)"""
        return {
            "encrypted": self.encrypted,
            "serial": self.serial,
            "button": self.buttons.generator_value,
            "vlow": int(self.vlow),
            "repeat": int(self.repeat),
        }

    def words(self) -> list[int]:
        """The three TX FIFO words: the 66 data bits in transmission order, LSB of the first word first.
        The upper 30 bits of the last word are not used."""
        bits = hcs300_bits(**self.fields())
        return [sum(bit << i for i, bit in enumerate(bits[start : start + 32])) for start in (0, 32, 64)]

    def frame(self) -> list[Segment]:
        """The frame the generator produces, as (level, PIO cycles): starts with a high pulse, ends with the
        low part of the last bit merged with the 39 TE guard time."""
        return hcs300_frame(TE_CYCLES, **self.fields())


@dataclass(frozen=True)
class Hcs300Tx:
    sm: SmProgram

    def __post_init__(self):
        options = self.sm.config.options
        if options.get("out_base", 0) != options.get("side_set_base", 0) or options.get("out_count") != 1:
            raise ValueError("the program drives one pin with both side-set and `mov pins`: out_base == side_set_base, out_count == 1")

    @property
    def pin(self) -> int:
        """GPIO the frame is driven on"""
        return self.sm.config.options.get("out_base", 0)

    @property
    def te_us(self) -> float:
        """Duration of one TE, from the clock of the program"""
        if self.sm.config.pio_hz is None:
            raise ValueError("the program has no clock")
        return TE_CYCLES / self.sm.config.pio_hz * 1e6

    def simulate(self, tx_words: Sequence[int], cycles: int) -> Trace:
        """Runs the program for `cycles` PIO cycles with these words in the TX FIFO from the start"""
        return run(self.sm, tx_words=tx_words, cycles=cycles)

    def transmit(self, codewords: Sequence[Hcs300Codeword], cycles: int) -> Trace:
        """Queues the three words of every code word and runs for `cycles` PIO cycles"""
        words = [word for codeword in codewords for word in codeword.words()]
        return self.simulate(words, cycles)

    def waveform(self, trace: Trace) -> list[Segment]:
        """The level of the frame pin over the whole run as (level, PIO cycles)"""
        return trace.output_segments(self.pin)

    @staticmethod
    def expected_waveform(codewords: Sequence[Hcs300Codeword], lead: int) -> list[Segment]:
        """What the pin shows for back to back frames: `lead` low cycles at the start, then every frame as the
        generator makes it, with the setup cycles of the program in between."""
        runs: list[Segment] = [(0, lead)]
        for index, codeword in enumerate(codewords):
            if index:
                runs.append((0, FRAME_SETUP_CYCLES))
            runs.extend(codeword.frame())
        return merge_runs(runs)
