"""HCS300 stimulus for the simulation tests.

Frames come from `test/system/hcs300_wf_gen.py`, the generator that drives the hardware test, so
simulation and bench see the same waveform.
"""

from __future__ import annotations

import importlib.util
from functools import cache

from .firmware import REPO_ROOT

GENERATOR = REPO_ROOT / "test" / "system" / "hcs300_wf_gen.py"


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
