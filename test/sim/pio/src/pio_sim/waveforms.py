"""HCS300 stimulus for the simulation tests.

Frames come from `test/system/hcs300_wf_gen.py`, the generator that drives the hardware test, so
simulation and bench see the same waveform.
"""

from __future__ import annotations

import importlib.util
from enum import STRICT, IntFlag
from functools import cache

from .programs import REPO_ROOT

GENERATOR = REPO_ROOT / "test" / "system" / "hcs300_wf_gen.py"


class Button(IntFlag, boundary=STRICT):
    """The four button inputs of the HCS300, as the 4-bit button status field of the code word (datasheet DS21137G
    figure 4-2: S2 S1 S0 S3 from MSb to LSb). That is the layout of `Hcs300ButtonStatus` in hcs300.rs as well, and
    the field is sent LSb first, so the order on the air is S3, S0, S1, S2. Combine buttons with `|`. A value
    with other bits raises ValueError (STRICT).

    The generator's `button` argument has another layout, bit i is S<i>: see `generator_value`.
    """

    S3 = 1
    S0 = 2
    S1 = 4
    S2 = 8

    @property
    def label(self) -> str:
        """Readable name, also for no button at all: "S3|S1", "none" """
        return self.name or "none"

    @property
    def generator_value(self) -> int:
        """The buttons as the `button` argument of `hcs300_wf_gen.py`: bit i is S<i>"""
        return sum(1 << index for index, button in enumerate((Button.S0, Button.S1, Button.S2, Button.S3)) if button in self)


@cache
def _generator():
    spec = importlib.util.spec_from_file_location("hcs300_wf_gen", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_lengths(samples: list[str]) -> list[tuple[int, int]]:
    """'0'/'1' samples (1 us each) -> [(level, duration in us)]"""
    runs: list[tuple[int, int]] = []
    for sample in samples:
        level = int(sample)
        if runs and runs[-1][0] == level:
            runs[-1] = (level, runs[-1][1] + 1)
        else:
            runs.append((level, 1))
    return runs


def merge_runs(segments: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Joins neighbouring segments of the same level"""
    runs: list[tuple[int, int]] = []
    for level, duration in segments:
        if runs and runs[-1][0] == level:
            runs[-1] = (level, runs[-1][1] + duration)
        else:
            runs.append((level, duration))
    return runs


def hcs300_frame(
    te_us: int,
    *,
    encrypted: int = 0xA5C3_1E96,
    serial: int = 0x0ABC_DEF1,
    button: int = 0b1010,
    vlow: int = 0,
    repeat: int = 1,
    trailing_idle_us: int = 0,
) -> list[tuple[int, int]]:
    """One code word as [(level, duration in us)], starting with a high pulse.

    It ends with the 39 TE guard time plus `trailing_idle_us`, all low, merged with the low part of
    the last data bit into one final run.
    """
    generator = _generator()
    sample_count = generator.calculate_waveform_duration_te() * te_us + trailing_idle_us
    samples = generator.generate_waveform(
        encrypted,
        serial,
        button,
        vlow,
        repeat,
        te_us,
        sample_count,
        sample_count,  # period in us == sample count -> 1 us per sample
    )
    return run_lengths(samples)


def hcs300_bits(encrypted: int, serial: int, button: int, vlow: int, repeat: int) -> list[int]:
    """The 66 data bits of a code word in transmission order (each field LSB first), from the generator."""
    return _generator().build_data_bits(encrypted, serial, button, vlow, repeat)
