"""PIO assembler for the simulation tests.

Understands the pioasm syntax that `pio_asm!` / `pio_file!` (embassy-rp, the Rust `pio-parser` crate)
accept: every instruction (jmp, wait, in, out, push, pull, mov, irq, set, nop, including the RP2350
forms `irq prev|next`, `mov pindirs` and `mov rxfifo[..]`) with delay and side-set, labels (also
`public`), `.define` with expressions, `.origin`, `.side_set <n> [opt] [pindirs]`,
`.wrap_target` / `.wrap`, `.program`, `.lang_opt` and `% c-sdk { ... %}` blocks.

On top of that it reads the program settings directives of the C++ pioasm of the pico-sdk, which
`pio-parser` rejects: `.clock_div`, `.fifo`, `.in`, `.out`, `.set`, `.mov_status` and `.pio_version`.
They do not change the opcodes, they end up in `Program` (see `Program.emulator_options()`).

Not supported (raises AssemblerError): `.word` and `wait jmppin`, which `pio-parser` rejects as well.

Where the Rust assembler panics on a program, this one raises AssemblerError. The encodings are verified
against the Rust assembler, see tests/test_assembler.py. The settings directives follow the grammar and the
range checks of the pioasm sources in the pico-sdk (tools/pioasm/parser.yy). No output is compared for them,
because pioasm is not built here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, NoReturn


class AssemblerError(ValueError):
    pass


@dataclass(frozen=True)
class ShiftConfig:
    """`.in` / `.out`: pin count, shift direction, autopush / autopull and its threshold"""

    count: int
    shift_right: bool = True
    auto: bool = False
    threshold: int = 32


@dataclass(frozen=True)
class MovStatus:
    """`.mov_status`: what `mov x, status` compares"""

    source: str
    """"txfifo" or "rxfifo": all ones while the FIFO holds fewer than `n` words. "irq": all ones while IRQ flag
    `n` is set (`irq prev set 2` is 8 + 2, `irq next set 2` is 16 + 2)"""
    n: int


@dataclass(frozen=True)
class Program:
    code: list[int]
    wrap_target: int
    wrap_top: int
    origin: int | None = None
    """.origin, the address the program has to be loaded at, None if it can be loaded anywhere"""
    side_set_count: int = 0
    """Side-set bits, without the enable bit of `opt`: `side_set_count` argument of pioemu"""
    side_set_opt: bool = False
    side_set_pindirs: bool = False
    public_defines: dict[str, int] = field(default_factory=dict)
    """`.define public` and `public` labels"""
    clock_div: float | None = None
    fifo: str | None = None
    """.fifo: txrx, tx, rx, txput, txget or putget"""
    pio_version: int | None = None
    in_shift: ShiftConfig | None = None
    out_shift: ShiftConfig | None = None
    set_count: int | None = None
    mov_status: MovStatus | None = None

    def emulator_options(self) -> dict:
        """The keyword arguments of `pioemu.emulate()` that follow from the program: wrap, side-set, shift
        configuration, set pin count and `mov ... status`. Pin bases, `jmp_pin` and `in_base` are up to the
        caller. FIFO joining (`.fifo`), the clock divider and side-set to pin directions are not modelled by
        pioemu and left out.
        """
        options: dict = {"wrap_target": self.wrap_target, "wrap_top": self.wrap_top}
        if self.side_set_count:
            options.update(side_set_count=self.side_set_count, side_set_opt=self.side_set_opt)
        if self.in_shift:
            options.update(
                auto_push=self.in_shift.auto,
                push_threshold=self.in_shift.threshold,
                shift_isr_right=self.in_shift.shift_right,
            )
        if self.out_shift:
            options.update(
                auto_pull=self.out_shift.auto,
                pull_threshold=self.out_shift.threshold,
                shift_osr_right=self.out_shift.shift_right,
                out_count=self.out_shift.count,
            )
        if self.set_count is not None:
            options["set_count"] = self.set_count
        if self.mov_status:
            if self.mov_status.source == "irq":
                raise ValueError("pioemu cannot select an IRQ flag as the source of mov ... status")
            options.update(
                status_sel=0 if self.mov_status.source == "txfifo" else 1,
                status_n=self.mov_status.n,
            )
        return options


_JMP_CONDITIONS = {"": 0, "!x": 1, "x--": 2, "!y": 3, "y--": 4, "x!=y": 5, "pin": 6, "!osre": 7}
_WAIT_SOURCES = {"gpio": 0, "pin": 1, "irq": 2}
_IN_SOURCES = {"pins": 0, "x": 1, "y": 2, "null": 3, "isr": 6, "osr": 7}
_OUT_DESTINATIONS = {"pins": 0, "x": 1, "y": 2, "null": 3, "pindirs": 4, "pc": 5, "isr": 6, "exec": 7}
_MOV_DESTINATIONS = {"pins": 0, "x": 1, "y": 2, "pindirs": 3, "exec": 4, "pc": 5, "isr": 6, "osr": 7}
_MOV_SOURCES = {"pins": 0, "x": 1, "y": 2, "null": 3, "status": 5, "isr": 6, "osr": 7}
_MOV_OPERATIONS = {"!": 1, "~": 1, "::": 2}
_SET_DESTINATIONS = {"pins": 0, "x": 1, "y": 2, "pindirs": 4}
_IRQ_MODIFIERS = {"set": 0b00, "nowait": 0b00, "wait": 0b01, "clear": 0b10}
_IRQ_INDEX_MODES = {"prev": 0b01, "rel": 0b10, "next": 0b11}
_RXFIFO = {"rxfifo[y]": 0b0000, "rxfifo[0]": 0b1000, "rxfifo[1]": 0b1001, "rxfifo[2]": 0b1010, "rxfifo[3]": 0b1011}

# Words the Rust lexer reserves: no label or define can have these names
_RESERVED = (
    {"nop", "jmp", "wait", "in", "out", "push", "pull", "mov", "irq", "set", "x", "y", "pins", "pin"}
    | {"gpio", "null", "isr", "osr", "pc", "exec", "pindirs", "block", "noblock", "status", "nowait"}
    | {"clear", "public", "iffull", "ifempty", "side", "osre", "opt", "rel", "prev", "next"}
)

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<number>0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]*\.[0-9]+|[0-9]+)
      | (?P<rxfifo>rxfifo\[(?:y|[0-3])\])
      | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
      | (?P<directive>\.[A-Za-z_][A-Za-z_0-9]*)
      | (?P<symbol>::|!=|--|[-+*/()\[\],:!~<])
    )""",
    re.VERBOSE,
)
_COMMENT = re.compile(r";.*|//.*")
# pioasm: these have to come before the first instruction
_BEFORE_INSTRUCTIONS = {".pio_version", ".fifo", ".in", ".out", ".set", ".mov_status"}
_FIFO_CONFIGS = {"txrx", "tx", "rx", "txput", "txget", "putget"}
_LANG_OPT = re.compile(r"\s*\.lang_opt\s", re.IGNORECASE)
_C_SDK_BLOCK = re.compile(r"% c-sdk \{[^%]*%\}")

_I32 = 1 << 32


@dataclass(frozen=True)
class _Token:
    kind: str  # number, rxfifo, name, directive or symbol
    text: str

    @property
    def word(self) -> str:
        """The text as the lexer matches keywords: case insensitive"""
        return self.text.lower() if self.kind in ("name", "directive") else self.text


@dataclass
class _Context:
    labels_and_defines: dict[str, int]
    public: dict[str, int]
    side_set_count: int  # without the enable bit
    side_set_opt: bool

    @property
    def side_set_bits(self) -> int:
        return self.side_set_count + self.side_set_opt


def assemble(source: str) -> Program:
    """Assembles a PIO program given as pioasm text."""
    # keep the line numbers of the lines after a c-sdk block
    source = _C_SDK_BLOCK.sub(lambda block: "\n" * block.group(0).count("\n"), source)

    context = _Context({}, {}, 0, False)
    pindirs = False
    origin: int | None = None
    wrap_target: int | None = None
    wrap_top: int | None = None
    clock_div: float | None = None
    fifo: str | None = None
    pio_version: int | None = None
    in_shift: ShiftConfig | None = None
    out_shift: ShiftConfig | None = None
    set_count: int | None = None
    mov_status: MovStatus | None = None
    instructions: list[tuple[int, list[_Token], str]] = []

    # first pass: labels, defines and directives, the instructions are encoded in the second pass
    for number, raw in enumerate(source.splitlines(), start=1):
        text = _COMMENT.sub("", raw)
        if _LANG_OPT.match(text):
            continue  # free text for other languages
        tokens = _tokenize(text, number)

        while tokens:
            public = len(tokens) >= 3 and tokens[0].word == "public" and tokens[2].text == ":"
            name_at = 1 if public else 0
            if not (len(tokens) > name_at + 1 and tokens[name_at].kind == "name" and tokens[name_at + 1].text == ":"):
                break
            name = _symbol_name(tokens[name_at], number)
            _define(context, name, len(instructions), public, number)
            tokens = tokens[name_at + 2 :]
        if not tokens:
            continue

        if tokens[0].kind != "directive":
            instructions.append((number, tokens, raw.strip()))
            continue

        directive, operands = tokens[0].word, _Parser(tokens[1:], context, number, text=raw.strip())
        if directive == ".program":
            if operands.more():
                operands.take()
            operands.end()
        elif directive == ".lang_opt":
            pass
        elif directive == ".define":
            public = operands.accept("public")
            name = _symbol_name(operands.take("a name"), number)
            value = operands.expression()
            operands.end()
            _define(context, name, value, public, number)
        elif directive == ".origin":
            origin = operands.value()
            operands.end()
            if not 0 <= origin <= 31:
                operands.fail(".origin must be 0..31")
        elif directive == ".side_set":
            if instructions:
                operands.fail(".side_set must come before the first instruction")
            count = operands.value()
            opt = operands.accept("opt")
            pindirs = operands.accept("pindirs")
            operands.end()
            if count < 0 or count + opt > 5:
                operands.fail("side-set takes at most 5 bits, including the one of opt")
            context.side_set_count, context.side_set_opt = count, opt
        elif directive == ".clock_div":
            number = operands.take("a divider")
            operands.end()
            if number.kind != "number":
                operands.fail("expected a number")
            clock_div = float(number.text) if "." in number.text else int(number.text, 0)
            if not 1 <= clock_div < 65536:
                operands.fail("clock divider must be between 1 and 65535")
        elif directive in _BEFORE_INSTRUCTIONS:
            if instructions:
                operands.fail(f"{directive} must precede any program instructions")
            if directive == ".pio_version":
                word = operands.take("a PIO version").word
                operands.end()
                if word not in ("0", "1", "rp2040", "rp2350"):
                    operands.fail("only PIO versions 0 (rp2040) and 1 (rp2350) are supported")
                pio_version = int(word) if word.isdigit() else int(word == "rp2350")
            elif directive == ".fifo":
                fifo = operands.keyword(_FIFO_CONFIGS, "txrx, tx, rx, txput, txget or putget")
                operands.end()
            elif directive == ".set":
                set_count = operands.value()
                operands.end()
                if not 0 <= set_count <= 5:
                    operands.fail("set pin count should be >= 0 and <= 5")
            elif directive == ".mov_status":
                source = operands.keyword({"txfifo", "rxfifo", "irq"}, "'txfifo < N', 'rxfifo < N' or 'irq set N'")
                if source == "irq":
                    offset = 8 if operands.accept("prev") else 16 if operands.accept("next") else 0
                    operands.expect("set")
                    n = operands.value()
                    operands.end()
                    if not 0 <= n <= 7:
                        operands.fail("irq number should be >= 0 and <= 7")
                    mov_status = MovStatus("irq", offset + n)
                else:
                    operands.expect("<")
                    n = operands.value()
                    operands.end()
                    if not 0 <= n <= 31:
                        operands.fail("fifo depth should be >= 0 and <= 31")
                    mov_status = MovStatus(source, n)
            else:  # .in and .out
                count = operands.value()
                shift_right = True
                if operands.peek() in ("left", "right"):
                    shift_right = operands.take().word == "right"
                auto = False
                if operands.peek() in ("auto", "manual"):
                    auto = operands.take().word == "auto"
                threshold = operands.value() if operands.more() else 32
                operands.end()
                lowest = 1 if directive == ".in" else 0
                if not lowest <= count <= 32:
                    operands.fail(f"pin count should be >= {lowest} and <= 32")
                if not 1 <= threshold <= 32:
                    operands.fail("threshold should be >= 1 and <= 32")
                if directive == ".in":
                    in_shift = ShiftConfig(count, shift_right, auto, threshold)
                else:
                    out_shift = ShiftConfig(count, shift_right, auto, threshold)
        elif directive in (".wrap_target", ".wrap"):
            operands.end()
            if directive == ".wrap_target":
                if wrap_target is not None:
                    operands.fail("duplicate .wrap_target")
                wrap_target = len(instructions)
            else:
                if wrap_top is not None:
                    operands.fail("duplicate .wrap")
                wrap_top = len(instructions) - 1
        else:
            raise AssemblerError(f"line {number}: unsupported directive {directive}: {raw.strip()!r}")

    if not instructions:
        raise AssemblerError("empty program")
    if len(instructions) > 32:
        raise AssemblerError(f"{len(instructions)} instructions do not fit in the 32 words of the instruction memory")
    if (wrap_target is None) != (wrap_top is None):
        raise AssemblerError(".wrap_target and .wrap must both be given or both left out")
    if wrap_target is None:
        wrap_target, wrap_top = 0, len(instructions) - 1
    if not 0 <= wrap_top < len(instructions) or not 0 <= wrap_target < len(instructions):
        raise AssemblerError(".wrap_target and .wrap must be around an instruction")

    if fifo not in (None, "rx", "tx", "txrx") and in_shift and in_shift.auto:
        raise AssemblerError(f"autopush is incompatible with .fifo {fifo}")

    code = [_encode(tokens, context, number, text) for number, tokens, text in instructions]
    return Program(
        code=code,
        wrap_target=wrap_target,
        wrap_top=wrap_top,
        origin=origin,
        side_set_count=context.side_set_count,
        side_set_opt=context.side_set_opt,
        side_set_pindirs=pindirs,
        public_defines=dict(context.public),
        clock_div=clock_div,
        fifo=fifo,
        pio_version=pio_version,
        in_shift=in_shift,
        out_shift=out_shift,
        set_count=set_count,
        mov_status=mov_status,
    )


def _tokenize(text: str, number: int) -> list[_Token]:
    tokens = []
    position = 0
    while text[position:].strip():
        found = _TOKEN.match(text, position)
        if not found:
            raise AssemblerError(f"line {number}: unexpected character {text[position:].strip()[0]!r}: {text.strip()!r}")
        kind = found.lastgroup
        tokens.append(_Token(kind, found.group(kind)))
        position = found.end()
    return tokens


def _symbol_name(token: _Token, number: int) -> str:
    if token.kind != "name" or token.word in _RESERVED:
        raise AssemblerError(f"line {number}: {token.text!r} is not a valid label or define name")
    return token.text


def _define(context: _Context, name: str, value: int, public: bool, number: int) -> None:
    if name in context.labels_and_defines:
        raise AssemblerError(f"line {number}: {name!r} is defined twice")
    context.labels_and_defines[name] = value
    if public:
        context.public[name] = value


class _Parser:
    """Recursive descent over the tokens of one line, following the grammar of pio-parser"""

    def __init__(self, tokens: list[_Token], context: _Context, number: int, text: str):
        self.tokens = tokens
        self.context = context
        self.number = number
        self.text = text
        self.position = 0

    def fail(self, message: str) -> NoReturn:
        raise AssemblerError(f"line {self.number}: {message}: {self.text!r}")

    def more(self) -> bool:
        return self.position < len(self.tokens)

    def peek(self, offset: int = 0) -> str | None:
        index = self.position + offset
        return self.tokens[index].word if index < len(self.tokens) else None

    def take(self, what: str = "more operands") -> _Token:
        if not self.more():
            self.fail(f"expected {what}")
        self.position += 1
        return self.tokens[self.position - 1]

    def accept(self, word: str) -> bool:
        if self.peek() == word:
            self.position += 1
            return True
        return False

    def expect(self, word: str) -> None:
        if not self.accept(word):
            self.fail(f"expected {word!r}")

    def keyword(self, choices: dict[str, int] | set[str], what: str) -> str:
        word = self.take(what).word
        if word not in choices:
            self.position -= 1
            self.fail(f"expected {what}")
        return word

    def end(self) -> None:
        if self.more():
            self.fail(f"unexpected {self.tokens[self.position].text!r}")

    # --- expressions ---

    def value(self) -> int:
        """A number, a label or define, or a parenthesized expression"""
        token = self.take("a value")
        if token.kind == "number":
            return int(token.text, 0)
        if token.kind == "name" and token.word not in _RESERVED:
            if token.text not in self.context.labels_and_defines:
                self.fail(f"unknown label or define {token.text!r}")
            return self.context.labels_and_defines[token.text]
        if token.text == "(":
            result = self.expression()
            self.expect(")")
            return result
        self.position -= 1
        self.fail("expected a value")

    def expression(self) -> int:
        result = self._term()
        while self.peek() in ("+", "-"):
            if self.take().text == "+":
                result = _wrap(result + self._term())
            else:
                result = _wrap(result - self._term())
        return result

    def _term(self) -> int:
        result = self._unary()
        while self.peek() in ("*", "/"):
            if self.take().text == "*":
                result = _wrap(result * self._unary())
            else:
                divisor = self._unary()
                if divisor == 0:
                    self.fail("division by zero")
                result = _wrap(int(result / divisor))  # truncates towards zero like Rust
        return result

    def _unary(self) -> int:
        if self.accept("-"):
            return _wrap(-self.value())
        if self.accept("::"):
            return _wrap(int(f"{self.value() % _I32:032b}"[::-1], 2))
        return self.value()


def _wrap(value: int) -> int:
    """Signed 32 bit arithmetic"""
    return (value + (_I32 >> 1)) % _I32 - (_I32 >> 1)


def _encode(tokens: list[_Token], context: _Context, number: int, text: str) -> int:
    p = _Parser(tokens, context, number, text)
    mnemonic = p.take().word
    operands = _operands(p, mnemonic)

    delay: int | None = None
    side: int | None = None
    while p.more():
        if p.accept("side"):
            if side is not None:
                p.fail("duplicate side")
            side = p.value()
        elif p.accept("["):
            if delay is not None:
                p.fail("duplicate delay")
            delay = p.expression()
            p.expect("]")
        else:
            p.fail(f"unexpected {p.tokens[p.position].text!r}")
    delay = delay or 0

    delay_max = (1 << (5 - context.side_set_bits)) - 1
    if not 0 <= delay <= delay_max:
        p.fail(f"delay must be 0..{delay_max}" + (" with this side-set" if context.side_set_bits else ""))
    if side is None:
        if context.side_set_bits and not context.side_set_opt:
            p.fail("instruction requires 'side'")
        side_bits = 0
    else:
        if not 0 <= side < (1 << context.side_set_count):
            p.fail(f"'side' must be 0..{(1 << context.side_set_count) - 1}")
        side_bits = side << (5 - context.side_set_bits)
        if context.side_set_opt:
            side_bits |= 0b10000
    return operands | ((delay | side_bits) << 8)


def _operands(p: _Parser, mnemonic: str) -> int:
    if mnemonic == "nop":
        return 0xA042  # mov y, y

    if mnemonic == "jmp":
        condition = ""
        if p.accept("!"):
            condition = "!" + p.keyword({"x", "y", "osre"}, "x, y or osre")
        elif p.peek() in ("x", "y"):
            condition = p.take().word
            if p.accept("--"):
                condition += "--"
            else:
                p.expect("!=")
                p.expect("y")
                condition += "!=y"
            if condition == "y!=y":
                p.fail("expected 'x--', 'y--' or 'x!=y'")
        elif p.accept("pin"):
            condition = "pin"
        if condition not in _JMP_CONDITIONS:
            p.fail("unknown jmp condition")
        p.accept(",")
        address = p.expression()
        if not 0 <= address <= 31:
            p.fail("jump target out of range")
        return (_JMP_CONDITIONS[condition] << 5) | address

    if mnemonic == "wait":
        polarity = p.value()
        source = p.keyword(_WAIT_SOURCES, "gpio, pin or irq")
        p.accept(",")
        index = p.value()
        relative = p.accept("rel")
        if polarity not in (0, 1):
            p.fail("wait polarity must be 0 or 1")
        if relative and source != "irq":
            p.fail("rel only goes with wait irq")
        if not 0 <= index <= (7 if source == "irq" else 31):
            p.fail("wait index out of range")
        return 0x2000 | (polarity << 7) | (_WAIT_SOURCES[source] << 5) | index | (0b10000 if relative else 0)

    if mnemonic in ("in", "out"):
        table = _IN_SOURCES if mnemonic == "in" else _OUT_DESTINATIONS
        target = p.keyword(table, f"an {mnemonic} operand")
        p.accept(",")
        count = p.value()
        if not 1 <= count <= 32:
            p.fail("bit count must be 1..32")
        return (0x4000 if mnemonic == "in" else 0x6000) | (table[target] << 5) | (count & 0x1F)

    if mnemonic in ("push", "pull"):
        conditional = p.accept("iffull" if mnemonic == "push" else "ifempty")
        block = True
        if p.accept("noblock"):
            block = False
        else:
            p.accept("block")
        return 0x8000 | (0x80 if mnemonic == "pull" else 0) | (0x40 if conditional else 0) | (0x20 if block else 0)

    if mnemonic == "mov":
        destination = p.take("a mov destination").word
        p.accept(",")
        operation = 0
        if p.peek() in _MOV_OPERATIONS:
            operation = _MOV_OPERATIONS[p.take().word]
        source = p.take("a mov source").word
        if source == "isr" and destination in _RXFIFO:
            return 0x8010 | _RXFIFO[destination]  # the operation has no effect
        if destination == "osr" and source in _RXFIFO:
            return 0x8090 | _RXFIFO[source]
        if destination not in _MOV_DESTINATIONS or source not in _MOV_SOURCES:
            p.fail("unknown or illegal mov operands")
        return 0xA000 | (_MOV_DESTINATIONS[destination] << 5) | (operation << 3) | _MOV_SOURCES[source]

    if mnemonic == "irq":
        modifier = p.accept("clear") and "clear"
        for name in ("set", "nowait", "wait"):
            if not modifier and p.accept(name):
                modifier = name
        index = p.value()
        mode = 0
        for name, bits in _IRQ_INDEX_MODES.items():
            if p.accept(name):
                mode = bits
                break
        if not 0 <= index <= 7:
            p.fail("irq index must be 0..7")
        return 0xC000 | (_IRQ_MODIFIERS[modifier or "set"] << 5) | (mode << 3) | index

    if mnemonic == "set":
        destination = p.keyword(_SET_DESTINATIONS, "set pins, x, y or pindirs")
        p.accept(",")
        value = p.value()
        if not 0 <= value <= 31:
            p.fail("set value must be 0..31")
        return 0xE000 | (_SET_DESTINATIONS[destination] << 5) | value

    p.position = 0
    p.fail(f"unsupported instruction {mnemonic!r}")
