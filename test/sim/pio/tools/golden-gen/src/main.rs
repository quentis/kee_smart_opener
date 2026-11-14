//! Assembles a list of PIO sources with the Rust `pio` assembler (the one behind embassy-rp's
//! `pio_asm!`) and prints the machine code as JSON. The output is `tests/golden_opcodes.json`,
//! which checks the Python assembler used by the simulation tests: opcodes, wrap, origin, side-set
//! settings and public defines.
//!
//! Regenerate with (from test/sim/pio):
//!     cargo run --manifest-path tools/golden-gen/Cargo.toml > tests/golden_opcodes.json

use pio_parser::Parser;
use std::collections::BTreeMap;

/// Every instruction form the Python assembler supports, one program each
const SINGLES: &[&str] = &[
    "jmp 31",
    "jmp x!=y, 5",
    "jmp pin, 5",
    "jmp !osre 5 [31]",
    "JMP X-- 3",
    "wait 1 pin, 3",
    "wait 1 irq 2 rel",
    "wait 0 irq 0 rel [2]",
    "irq 3",
    "irq set 3",
    "irq nowait 3",
    "irq wait 3",
    "irq clear 3",
    "irq 2 rel",
    "irq wait 1 rel",
    "irq clear 7 rel",
    "irq set 1 prev",
    "irq wait 2 next",
    "irq clear 0 next [4]",
    "IRQ WAIT 5",
    "in pins, 32",
    "in x,8",
    "mov pindirs, x",
    "mov pins, status",
    "mov isr, ::osr",
    "mov pindirs, ~null",
    "mov x !y",
    "mov x ~y",
    "mov x, ::y",
    "MOV X, Y",
    "mov rxfifo[y], isr",
    "mov rxfifo[0], isr",
    "mov rxfifo[1], isr",
    "mov rxfifo[2], isr",
    "mov rxfifo[3], isr",
    "mov osr, rxfifo[y]",
    "mov osr, rxfifo[0]",
    "mov osr, rxfifo[1]",
    "mov osr, rxfifo[2]",
    "mov osr, rxfifo[3]",
    "mov x, y [31]",
    "set x,5",
    "Set X, 1",
    "set pins, 1 [31]",
    "push iffull noblock [31]",
    "pull ifempty block [1]",
    "pull noblock",
    "jmp 5",
    "jmp !x 5",
    "jmp x-- 5",
    "jmp !y 5",
    "jmp y-- 5",
    "jmp x!=y 5",
    "jmp pin 5",
    "jmp !osre 5",
    "jmp x-- 7 [3]",
    "wait 0 gpio 5",
    "wait 1 gpio 31",
    "wait 0 pin 0",
    "wait 1 pin 7 [3]",
    "wait 1 irq 2",
    "wait 0 irq 7",
    "in pins, 1",
    "in x, 32",
    "in x 32",
    "in y, 8",
    "in null, 31",
    "in isr, 16",
    "in osr, 2",
    "in x, 32 [4]",
    "out pins, 8",
    "out x, 1",
    "out y, 32",
    "out null, 19",
    "out pindirs, 4",
    "out pc, 5",
    "out isr, 3",
    "out exec, 16",
    "push",
    "push block",
    "push noblock",
    "push iffull",
    "push iffull block",
    "push iffull noblock",
    "push noblock [2]",
    "pull",
    "pull block",
    "pull noblock",
    "pull ifempty",
    "pull ifempty block",
    "pull ifempty noblock",
    "pull [1]",
    "mov x, osr",
    "mov y, osr",
    "mov osr, ~null",
    "mov x, ~x",
    "mov x, !y",
    "mov y, ::x",
    "mov isr, x",
    "mov osr, isr",
    "mov pc, x",
    "mov exec, y",
    "mov pins, x",
    "mov x, pins",
    "mov x, status",
    "mov y, null",
    "mov x, y [5]",
    "set pins, 1",
    "set x, 31",
    "set y, 0",
    "set pindirs, 7",
    "set x, 5 [2]",
    "nop",
    "nop [3]",
];

/// Whole programs: labels, forward references, delays and wrap. Includes the generations of the
/// HCS300 capture program that were evaluated, the last one is the firmware's.
const PROGRAMS: &[(&str, &str)] = &[
    (
        "hcs300 v2: idle wait only, 2 cycles per tick",
        "pull
.wrap_target
idle:
    wait 1 pin 0
high:
    mov x, osr
hi_loop:
    jmp x-- hi_chk
    jmp timeout
hi_chk:
    jmp pin hi_loop
    in x, 32
    push noblock
    mov x, osr
lo_loop:
    jmp pin rising
    jmp x-- lo_loop
timeout:
    in x, 32
    push noblock
    wait 0 pin 0
    jmp idle
rising:
    in x, 32
    push noblock
    jmp high
.wrap
",
    ),
    (
        "hcs300 v3: arm state, timeout built in the program",
        "mov osr, ~null
out null, 19
.wrap_target
arm:
    mov x, osr
arm_loop:
    jmp pin arm
    jmp x-- arm_loop
idle:
    wait 1 pin 0
high:
    mov x, osr
hi_loop:
    jmp x-- hi_chk
    jmp stuck
hi_chk:
    jmp pin hi_loop
    in x, 32
    push noblock
    mov x, osr
lo_loop:
    jmp pin rising
    jmp x-- lo_loop
    in x, 32
    push noblock
    jmp idle
rising:
    in x, 32
    push noblock
    jmp high
stuck:
    in x, 32
    push noblock
.wrap
",
    ),
    (
        "hcs300 v4: preloaded T-2 in y",
        "pull
mov y, osr
jmp y-- dec1
dec1:
jmp y-- dec2
dec2:
.wrap_target
idle:
    wait 1 pin 0 [3]
high:
    mov x, y
hi_loop:
    jmp x-- hi_chk
    jmp timeout
hi_chk:
    jmp pin hi_loop
    in x, 32
    push noblock
    mov x, y
lo_loop:
    jmp pin rising
    jmp x-- lo_loop
timeout:
    in x, 32
    push noblock
    wait 0 pin 0
    jmp idle
rising:
    in x, 32
    push noblock
    jmp high
.wrap
",
    ),
    (
        "hcs300 v5: 5 cycles per tick, balanced edge handlers",
        "pull
.wrap_target
idle:
    wait 1 pin 0 [3]
high:
    mov x, osr
    jmp x-- hi_loop
hi_loop:
    jmp x-- hi_chk [3]
    jmp timeout
hi_chk:
    jmp pin hi_loop
    in x, 32
    push noblock
    mov x, osr
    jmp x-- lo_loop
lo_loop:
    jmp pin rising
    jmp x-- lo_loop [3]
timeout:
    in x, 32
    push noblock
    wait 0 pin 0
    jmp idle
rising:
    in x, 32
    push noblock
    jmp high
.wrap
",
    ),
    (
        "side-set 2 bits, required: side before and after the delay",
        ".side_set 2
    set pins, 1 side 3
    nop side 0 [7]
    jmp 0 [3] side 1
    wait 1 pin 0 side 2 [2]
    irq wait 4 rel side 0
    push side 1
    pull noblock side 2
",
    ),
    (
        "side-set 1 bit, optional",
        ".side_set 1 opt
    set pins, 1 side 1
    nop
    nop [7]
    jmp 0 side 0 [3]
    mov x, y side 1
",
    ),
    (
        "side-set 3 bits, optional, pindirs",
        ".side_set 3 opt pindirs
    nop side 5 [1]
    nop side 7
    nop [1]
    nop
",
    ),
    (
        "side-set 5 bits",
        ".side_set 5
    nop side 31
    jmp 1 side 0
",
    ),
    (
        "defines, expressions, origin, public labels",
        ".define DELAY 3
.define BITS 8
.define public TE BITS * 2 + 3
.define public SPAN (TE - 1) / 2
.define public MIXED 7 - 2 - 1
.define public NEGATIVE -4 + 9
.define public REVERSED ::0x1
.define public HEX 0x1F
.define public BIN 0b101
.origin 8
public entry:
    set x, 1 [DELAY]
loop:
    out pins, BITS
    set y, (BITS - 1) [DELAY - 1]
    jmp x-- loop
    jmp end - 1
    jmp TE - 13
    in x, (HEX + 1)
public end:
    irq wait (HEX - 28)
",
    ),
    (
        "case insensitive keywords, case sensitive labels",
        ".WRAP_TARGET
Start:
    SET X, 3
Loop:
    JMP X-- Loop [1]
    jmp start_
start_:
    Nop
.WRAP
",
    ),
    (
        "lang_opt and c-sdk block, program in a file",
        ".define public FILE_LEVEL 2
.program blink
.lang_opt python sideset_init = pico.PIO.OUT_LOW
.side_set 1
.wrap_target
    set pins, 1 side 0 [FILE_LEVEL]
    set pins, 0 side 1 [FILE_LEVEL]
.wrap
% c-sdk {
static inline void blink_program_init(PIO pio) {
    pio_gpio_init(pio, 0);
}
%}
",
    ),
    (
        "hcs300 tx (without the directives pio-parser does not know)",
        ".side_set 1 opt
    set x, 1
    in x, 6
    in x, 1
.wrap_target
wait_start:
    mov x, ~status
    jmp !x wait_start
    set x, 11 side 0
preamble:
    nop side 0 [1]
    jmp x-- preamble side 1 [1]
    set x, 17 side 0
sync:
    jmp x-- sync
    mov x, ::isr
pwm:
    out y, 1 side 1 [1]
    mov pins, ~y [1]
    jmp x-- pwm side 0 [1]
pwm_end:
    out y, 30
    set x, 8 [4]
guard:
    jmp x-- guard [7]
.wrap
",
    ),
    (
        "comments and default wrap",
        "start:
    set x, 3 ; comment
loop:
    jmp x-- loop // comment
    nop
",
    ),
];

fn json_string(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn entry(name: &str, source: &str) -> String {
    // the parser wants every line terminated, pio_asm! joins its strings with newlines as well
    let text = format!("{source}
");
    let parsed = if source.contains(".program") {
        // what pio_file! uses
        let file = Parser::<32>::parse_file(&text)
            .unwrap_or_else(|e| panic!("cannot assemble {source:?}: {e:?}"));
        assert_eq!(file.len(), 1, "one .program per source");
        file.into_values().next().unwrap()
    } else {
        Parser::<32>::parse_program(&text)
            .unwrap_or_else(|e| panic!("cannot assemble {source:?}: {e:?}"))
    };
    let program = parsed.program;
    let code: Vec<String> = program.code.iter().map(|w| w.to_string()).collect();
    let defines: BTreeMap<_, _> = parsed.public_defines.iter().collect();
    let defines: Vec<String> = defines
        .iter()
        .map(|(name, value)| format!("{}: {}", json_string(name), value))
        .collect();
    let side_set = program.side_set;
    format!(
        "  {{\"name\": {}, \"source\": {}, \"code\": [{}], \"wrap_target\": {}, \"wrap_top\": {}, \"origin\": {}, \"side_set_count\": {}, \"side_set_opt\": {}, \"side_set_pindirs\": {}, \"public_defines\": {{{}}}}}",
        json_string(name),
        json_string(source),
        code.join(", "),
        program.wrap.target,
        program.wrap.source,
        program.origin.map_or("null".to_string(), |o| o.to_string()),
        side_set.bits() - side_set.optional() as u8,
        side_set.optional(),
        side_set.pindirs(),
        defines.join(", "),
    )
}

fn main() {
    let mut entries: Vec<String> = SINGLES.iter().map(|s| entry(s, s)).collect();
    entries.extend(PROGRAMS.iter().map(|(name, source)| entry(name, source)));
    println!("[\n{}\n]", entries.join(",\n"));
}
