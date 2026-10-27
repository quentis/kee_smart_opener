"""Reads the HCS300 pulse measurement PIO program and its settings out of the firmware sources.

The program is the .pio file that main.rs includes with pio_file!(), the settings are constants in
main.rs, so there is no second copy to keep in sync. Set KSO_FIRMWARE_DIR to use another copy of the
firmware crate.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .assembler import Program, assemble

# test/sim/pio/src/pio_sim/firmware.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[5]
FIRMWARE_DIR = Path(os.environ.get("KSO_FIRMWARE_DIR", REPO_ROOT / "sw" / "kso-fw-rs"))
MAIN_RS = FIRMWARE_DIR / "src" / "main.rs"

SETUP_FUNCTION = "setup_pio_task_sm0"


@dataclass(frozen=True)
class Firmware:
    program: Program
    source: str
    """PIO assembly, the content of the .pio file"""
    timeout_ticks: int
    """HCS300_TIMEOUT_TICKS: value pushed to the TX FIFO, ticks until a level counts as idle"""
    sentinel: int
    """HCS300_PIO_SENTINEL: word the Rust side treats as idle/stuck marker"""
    pio_hz: int
    """PIO clock, from calculate_pio_clock_divider()"""

    @property
    def cycles_per_us(self) -> int:
        """PIO cycles per microsecond. The firmware contract is: 1 tick = 1 us."""
        if self.pio_hz % 1_000_000:
            raise ValueError(f"PIO clock {self.pio_hz} Hz is not a whole number of cycles per us")
        return self.pio_hz // 1_000_000


def load_firmware(path: Path = MAIN_RS) -> Firmware:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise FileNotFoundError(f"firmware source not found: {path} (set KSO_FIRMWARE_DIR)") from error

    function = re.search(rf"\bfn\s+{SETUP_FUNCTION}\b", text)
    if not function:
        raise ValueError(f"{path}: function {SETUP_FUNCTION} not found")

    macro = re.compile(r"\bpio_file!\s*\(\s*\"([^\"]+)\"\s*([,)])").search(text, function.end())
    if not macro:
        raise ValueError(f"{path}: no pio_file!(\"...\") program in {SETUP_FUNCTION}")
    if macro.group(2) == ",":
        raise ValueError(f"{path}: pio_file! options (select_program, ...) are not supported by the tests")

    # like the macro, a relative path is relative to the crate directory
    pio_path = path.parent.parent / macro.group(1)
    try:
        source = pio_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise FileNotFoundError(f"PIO program not found: {pio_path}") from error
    if len(re.findall(r"^\s*\.program\b", source, re.MULTILINE)) != 1:
        raise ValueError(f"{pio_path}: the tests support exactly one .program per file")

    clock = re.compile(r"calculate_pio_clock_divider\(\s*([0-9_]+)\s*\)").search(text, function.end())
    if not clock:
        raise ValueError(f"{path}: calculate_pio_clock_divider() not found in {SETUP_FUNCTION}")

    return Firmware(
        program=assemble(source),
        source=source,
        timeout_ticks=_constant(text, "HCS300_TIMEOUT_TICKS"),
        sentinel=_constant(text, "HCS300_PIO_SENTINEL"),
        pio_hz=int(clock.group(1).replace("_", "")),
    )


def _constant(text: str, name: str) -> int:
    found = re.search(rf"\bconst\s+{name}\s*:\s*u32\s*=\s*([^;]+);", text)
    if not found:
        raise ValueError(f"const {name}: u32 not found")
    value = found.group(1).strip().replace("_", "")
    if value == "u32::MAX":
        return 0xFFFF_FFFF
    return int(value, 0)
