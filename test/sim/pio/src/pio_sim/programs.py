"""Loads PIO programs from .pio files together with their state machine settings.

Nothing here knows the firmware's Rust code: the program is the .pio file, the settings are in the file
as well (see config.py). Set KSO_PIO_DIR to use another directory than `sw/kso-fw-rs/pio`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .assembler import Program, assemble
from .config import SmConfig, build_config

# test/sim/pio/src/pio_sim/programs.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[5]
PIO_DIR = Path(os.environ.get("KSO_PIO_DIR", REPO_ROOT / "sw" / "kso-fw-rs" / "pio"))


@dataclass(frozen=True)
class SmProgram:
    """An assembled PIO program and the settings of the state machine that runs it"""

    path: Path
    source: str
    """PIO assembly, the content of the .pio file"""
    program: Program
    config: SmConfig

    @property
    def cycles_per_us(self) -> int:
        return self.config.cycles_per_us

    def configured(self, **overrides) -> "SmProgram":
        """A copy with settings of the test applied, see `SmConfig.with_overrides()`: `clock_hz` or `clock_div`,
        the pin mapping (`in_base`, `out_base`, ...) and the shift settings."""
        return replace(self, config=self.config.with_overrides(**overrides))


def pio_files(directory: Path = PIO_DIR) -> list[Path]:
    return sorted(directory.glob("*.pio"))


def load_program(file: str | Path) -> SmProgram:
    """Loads a .pio file, given as a path or as a file name in the PIO directory"""
    path = Path(file)
    if not path.is_absolute() and not path.exists():
        path = PIO_DIR / path
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise FileNotFoundError(f"PIO program not found: {path} (set KSO_PIO_DIR)") from error

    return from_source(source, path)


def from_source(source: str, path: Path = Path("<inline>")) -> SmProgram:
    """Like load_program(), for PIO assembly given as text"""
    if len(re.findall(r"^\s*\.program\b", source, re.MULTILINE)) > 1:
        raise ValueError(f"{path}: the tests support at most one .program per file")

    program = assemble(source)
    return SmProgram(path=path, source=source, program=program, config=build_config(program))
