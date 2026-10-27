//! Assembles a list of PIO sources with the Rust `pio` assembler (the one behind embassy-rp's
//! `pio_asm!`) and prints the machine code as JSON. The output is `tests/golden_opcodes.json`,
//! which checks the Python assembler used by the simulation tests.
//!
//! Regenerate with (from test/sim/pio):
//!     cargo run --manifest-path tools/golden-gen/Cargo.toml > tests/golden_opcodes.json

use pio_parser::Parser;

/// Every instruction form the Python assembler supports, one program each
const SINGLES: &[&str] = &[
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
    let parsed = Parser::<32>::parse_program(&format!("{source}\n"))
        .unwrap_or_else(|e| panic!("cannot assemble {source:?}: {e:?}"));
    let program = parsed.program;
    let code: Vec<String> = program.code.iter().map(|w| w.to_string()).collect();
    format!(
        "  {{\"name\": {}, \"source\": {}, \"code\": [{}], \"wrap_target\": {}, \"wrap_top\": {}}}",
        json_string(name),
        json_string(source),
        code.join(", "),
        program.wrap.target,
        program.wrap.source,
    )
}

fn main() {
    let mut entries: Vec<String> = SINGLES.iter().map(|s| entry(s, s)).collect();
    entries.extend(PROGRAMS.iter().map(|(name, source)| entry(name, source)));
    println!("[\n{}\n]", entries.join(",\n"));
}
