"""Minimal PIO assembler for the simulation tests.

Understands the pioasm syntax that `pio_asm!` (embassy-rp / the Rust `pio` crate) accepts, for the
instructions `pioemu` can simulate: jmp, wait, in, out, push, pull, mov, set and nop, with delays,
labels and `.wrap_target` / `.wrap`.

Not supported (raises AssemblerError): irq, side-set, .origin, .define and friends. `pioemu` has no IRQ
model, and the firmware program does not use them.

The encodings are verified against the Rust `pio` crate, see tests/test_assembler.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class AssemblerError(ValueError):
    pass


@dataclass(frozen=True)
class Program:
    code: list[int]
    wrap_target: int
    wrap_top: int


_JMP_CONDITIONS = {"": 0, "!x": 1, "x--": 2, "!y": 3, "y--": 4, "x!=y": 5, "pin": 6, "!osre": 7}
_WAIT_SOURCES = {"gpio": 0, "pin": 1, "irq": 2}
_IN_SOURCES = {"pins": 0, "x": 1, "y": 2, "null": 3, "isr": 6, "osr": 7}
_OUT_DESTINATIONS = {"pins": 0, "x": 1, "y": 2, "null": 3, "pindirs": 4, "pc": 5, "isr": 6, "exec": 7}
_MOV_DESTINATIONS = {"pins": 0, "x": 1, "y": 2, "exec": 4, "pc": 5, "isr": 6, "osr": 7}
_MOV_SOURCES = {"pins": 0, "x": 1, "y": 2, "null": 3, "status": 5, "isr": 6, "osr": 7}
_SET_DESTINATIONS = {"pins": 0, "x": 1, "y": 2, "pindirs": 4}

_DELAY = re.compile(r"\[\s*(\w+)\s*\]")
_LABEL = re.compile(r"^\s*([A-Za-z_]\w*)\s*:\s*(.*)$")


def assemble(source: str) -> Program:
    """Assembles a PIO program given as pioasm text (one instruction, label or directive per line)."""
    lines: list[tuple[int, str]] = []  # (source line number, instruction text)
    labels: dict[str, int] = {}
    wrap_target: int | None = None
    wrap_top: int | None = None

    for number, raw in enumerate(source.splitlines(), start=1):
        text = re.split(r";|//", raw, maxsplit=1)[0].strip()
        while text:
            label = _LABEL.match(text)
            if not label:
                break
            labels[label.group(1)] = len(lines)
            text = label.group(2).strip()
        if not text:
            continue

        if text.startswith("."):
            directive = text.split()[0].lower()
            if directive == ".wrap_target":
                wrap_target = len(lines)
            elif directive == ".wrap":
                wrap_top = len(lines) - 1
            elif directive != ".program":
                raise AssemblerError(f"line {number}: unsupported directive {directive}")
            continue

        lines.append((number, text))

    if not lines:
        raise AssemblerError("empty program")

    code = [_encode(text, labels, number) for number, text in lines]
    return Program(
        code=code,
        wrap_target=0 if wrap_target is None else wrap_target,
        wrap_top=len(code) - 1 if wrap_top is None else wrap_top,
    )


def _encode(text: str, labels: dict[str, int], number: int) -> int:
    def fail(message: str):
        raise AssemblerError(f"line {number}: {message}: {text!r}")

    delay = 0
    found = _DELAY.search(text)
    if found:
        delay = _number(found.group(1), labels, fail)
        text = _DELAY.sub("", text)
        if not 0 <= delay <= 31:
            fail("delay must be 0..31")

    tokens = [t for t in re.split(r"[,\s]+", text.strip().lower()) if t]
    mnemonic, operands = tokens[0], tokens[1:]
    word = delay << 8

    if mnemonic == "jmp":
        if not operands:
            fail("missing jump target")
        condition = "".join(operands[:-1])
        if condition not in _JMP_CONDITIONS:
            fail(f"unknown jmp condition {condition!r}")
        address = _number(operands[-1], labels, fail)
        if not 0 <= address <= 31:
            fail("jump target out of range")
        return word | (_JMP_CONDITIONS[condition] << 5) | address

    if mnemonic == "wait":
        if len(operands) != 3:
            fail("expected: wait <0|1> <gpio|pin|irq> <index>")
        polarity, source, index = operands
        if polarity not in ("0", "1") or source not in _WAIT_SOURCES:
            fail("bad wait operands")
        index = _number(index, labels, fail)
        if not 0 <= index <= 31:
            fail("wait index out of range")
        return 0x2000 | word | (int(polarity) << 7) | (_WAIT_SOURCES[source] << 5) | index

    if mnemonic in ("in", "out"):
        if len(operands) != 2:
            fail(f"expected: {mnemonic} <target>, <bit count>")
        table = _IN_SOURCES if mnemonic == "in" else _OUT_DESTINATIONS
        if operands[0] not in table:
            fail(f"unknown {mnemonic} operand {operands[0]!r}")
        count = _number(operands[1], labels, fail)
        if not 1 <= count <= 32:
            fail("bit count must be 1..32")
        base = 0x4000 if mnemonic == "in" else 0x6000
        return base | word | (table[operands[0]] << 5) | (count & 0x1F)

    if mnemonic in ("push", "pull"):
        flags = set(operands)
        allowed = {"iffull", "block", "noblock"} if mnemonic == "push" else {"ifempty", "block", "noblock"}
        if not flags <= allowed or {"block", "noblock"} <= flags or len(flags) != len(operands):
            fail("bad flags")
        conditional = "iffull" if mnemonic == "push" else "ifempty"
        return (
            0x8000
            | word
            | (0x80 if mnemonic == "pull" else 0)
            | (0x40 if conditional in flags else 0)
            | (0 if "noblock" in flags else 0x20)
        )

    if mnemonic == "mov":
        if len(operands) < 2:
            fail("expected: mov <destination>, [!|~|::]<source>")
        destination, source = operands[0], "".join(operands[1:])
        operation = 0
        if source.startswith(("~", "!")):
            operation, source = 1, source[1:]
        elif source.startswith("::"):
            operation, source = 2, source[2:]
        if destination not in _MOV_DESTINATIONS or source not in _MOV_SOURCES:
            fail("unknown mov operand")
        return (
            0xA000
            | word
            | (_MOV_DESTINATIONS[destination] << 5)
            | (operation << 3)
            | _MOV_SOURCES[source]
        )

    if mnemonic == "set":
        if len(operands) != 2 or operands[0] not in _SET_DESTINATIONS:
            fail("expected: set <pins|x|y|pindirs>, <value>")
        value = _number(operands[1], labels, fail)
        if not 0 <= value <= 31:
            fail("set value must be 0..31")
        return 0xE000 | word | (_SET_DESTINATIONS[operands[0]] << 5) | value

    if mnemonic == "nop":
        if operands:
            fail("nop takes no operands")
        return 0xA042 | word  # mov y, y

    fail(f"unsupported instruction {mnemonic!r}")


def _number(token: str, labels: dict[str, int], fail) -> int:
    if token in labels:
        return labels[token]
    try:
        return int(token, 0)
    except ValueError:
        fail(f"unknown label or number {token!r}")
