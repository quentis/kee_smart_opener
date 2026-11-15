"""State machine settings of a PIO program: from the .pio file, overridable by the test.

Layers, later ones win:

1. pioemu defaults,
2. what the program text says: `.wrap_target` / `.wrap`, `.side_set`, and the settings directives of the C++
   pioasm (`.in`, `.out`, `.set`, `.mov_status`, `.clock_div`), see `Program.emulator_options()`,
3. `.lang_opt sim <name> = <value>` lines. Both `pio-parser` (`pio_file!`, `pio_asm!`) and the C++ pioasm ignore
   them, so a file the firmware builds can still carry them. They cover what has no directive: the clock and
   the pin mapping, and they can override the settings of layer 2,
4. the test: `SmConfig.with_overrides()`, or `SmProgram.configured()`, with the same names. For programs whose
   clock or pins are up to the user, like a PIO SPI, the file says nothing and each test sets them.

The `sim` options:

- `clock_hz`: PIO clock in Hz. `clock_div`: PIO clock as the divider of the system clock, which is
  `SYS_CLOCK_HZ` for the whole simulation. A file that gives a clock in more than one way (also with
  `.clock_div`) has to be consistent, a test override replaces the clock of the file.
- `in_base`, `jmp_pin`, `out_base`, `out_count`, `set_base`, `set_count`, `side_set_base`: pin mapping, as in
  `pioemu.emulate()`.
- `auto_pull`, `auto_push`, `pull_threshold`, `push_threshold`, `shift_osr_right`, `shift_isr_right`,
  `status_sel`, `status_n`: shift and status settings, as in `pioemu.emulate()`.

In the file, values are integers (`0x10` works) or `true` / `false`, and `clock_div` may be a decimal. Example:

    .lang_opt sim clock_hz = 5000000
    .lang_opt sim jmp_pin = 0

The emulator has no clock divider, the clock only turns PIO cycles into time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from .assembler import Program

SYS_CLOCK_HZ = float(os.environ.get("KSO_SYS_CLOCK_HZ", 150_000_000))
"""System clock the dividers refer to: the default of the RP2350 that the firmware runs on"""

_INT_OPTIONS = {
    "in_base",
    "jmp_pin",
    "out_base",
    "out_count",
    "set_base",
    "set_count",
    "side_set_base",
    "pull_threshold",
    "push_threshold",
    "status_sel",
    "status_n",
}
_BOOL_OPTIONS = {"auto_pull", "auto_push", "shift_osr_right", "shift_isr_right"}
_CLOCK_OPTIONS = {"clock_hz", "clock_div"}
SIM_OPTIONS = _INT_OPTIONS | _BOOL_OPTIONS | _CLOCK_OPTIONS


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SmConfig:
    pio_hz: float | None
    """PIO clock, None if nothing gives one"""
    options: dict
    """Keyword arguments for `pioemu.emulate()`, without the input source"""
    sys_clock_hz: float = SYS_CLOCK_HZ

    @property
    def cycles_per_us(self) -> int:
        """PIO cycles per microsecond, for the programs whose clock is a whole number of MHz"""
        if self.pio_hz is None:
            raise ConfigError("no PIO clock: give `.lang_opt sim clock_hz = <Hz>`, `.clock_div` or a test override")
        if self.pio_hz % 1_000_000:
            raise ConfigError(f"PIO clock {self.pio_hz} Hz is not a whole number of cycles per us")
        return int(self.pio_hz) // 1_000_000

    def with_overrides(self, **overrides) -> SmConfig:
        """A copy with settings of the test applied: any `sim` option by its name, as a Python value. The other
        settings stay, a clock replaces the clock of the file."""
        options = dict(self.options)
        clock_hz = self.pio_hz
        clocks = [name for name in ("clock_hz", "clock_div") if name in overrides]
        if len(clocks) > 1:
            raise ConfigError("give either clock_hz or clock_div, not both")

        for name, value in overrides.items():
            if name not in SIM_OPTIONS:
                raise ConfigError(f"unknown option {name!r}, known are {', '.join(sorted(SIM_OPTIONS))}")
            if name in _BOOL_OPTIONS:
                if not isinstance(value, bool):
                    raise ConfigError(f"{name} must be True or False, not {value!r}")
                options[name] = value
            elif name == "clock_hz":
                clock_hz = _positive(name, value)
            elif name == "clock_div":
                clock_hz = self.sys_clock_hz / _positive(name, value)
            else:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ConfigError(f"{name} must be an integer, not {value!r}")
                options[name] = value
        return replace(self, pio_hz=clock_hz, options=options)


def build_config(program: Program, sys_clock_hz: float = SYS_CLOCK_HZ) -> SmConfig:
    """Settings of the state machine that runs `program`, from its text and its `.lang_opt sim` lines"""
    options = program.emulator_options()
    clocks: dict[str, float] = {}
    if program.clock_div is not None:
        clocks[".clock_div"] = sys_clock_hz / program.clock_div

    for name, text in program.lang_opts.get("sim", {}).items():
        if name not in SIM_OPTIONS:
            raise ConfigError(f".lang_opt sim {name}: unknown option, known are {', '.join(sorted(SIM_OPTIONS))}")
        if name in _BOOL_OPTIONS:
            options[name] = _boolean(name, text)
        elif name == "clock_hz":
            clocks[".lang_opt sim clock_hz"] = _positive(name, _number(name, text))
        elif name == "clock_div":
            clocks[".lang_opt sim clock_div"] = sys_clock_hz / _positive(name, _number(name, text))
        else:
            options[name] = _integer(name, text)

    values = list(clocks.values())
    if any(abs(value - values[0]) > 1e-9 * values[0] for value in values):
        found = ", ".join(f"{source} = {value:g} Hz" for source, value in clocks.items())
        raise ConfigError(f"the clock is given more than once and the values differ: {found}")
    return SmConfig(pio_hz=values[0] if values else None, options=options, sys_clock_hz=sys_clock_hz)


def _positive(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{name} must be a positive number, not {value!r}")
    return value


def _integer(name: str, text: str) -> int:
    try:
        return int(text, 0)
    except ValueError:
        raise ConfigError(f".lang_opt sim {name} = {text}: expected an integer") from None


def _number(name: str, text: str) -> float:
    try:
        return int(text, 0)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        raise ConfigError(f".lang_opt sim {name} = {text}: expected a number") from None


def _boolean(name: str, text: str) -> bool:
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    raise ConfigError(f".lang_opt sim {name} = {text}: expected true or false")
