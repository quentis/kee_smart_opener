# PIO simulation tests

Simulation tests of the PIO programs of `sw/kso-fw-rs` (the HCS300 capture program, which measures the
pulses, and the HCS300 transmitter). They run on
[pioemu](https://github.com/quentis/rp2040-pio-emulator/tree/dev), a Python PIO emulator, so no hardware is needed.
The `dev` branch of that fork is used (the upstream release plus IRQ support and fixes of the instruction
semantics found by cross-checking against a Pico 2, see its `CHANGELOG.md`), see `tool.uv.sources` in `pyproject.toml`.

## Run

Install [uv](https://docs.astral.sh/uv/), then from this directory:

```sh
uv run pytest
```

uv creates `.venv`, installs the dependencies from `uv.lock` (pioemu, pytest) and runs the tests. A full
run takes about 40 s, the emulator is slow.

## How a program is simulated

Any `.pio` file works, the tests never read the firmware's Rust code. `pio_sim.programs.load_program("name.pio")`
loads a file from `sw/kso-fw-rs/pio` (set `KSO_PIO_DIR` for another directory, or pass a path), assembles it
and builds the state machine settings. The settings come from the file, in layers, later ones win
(`src/pio_sim/config.py`):

1. pioemu defaults;
2. the program text: `.wrap_target` / `.wrap`, `.side_set`, and the settings directives of the C++ pioasm
   (`.clock_div`, `.fifo`, `.in`, `.out`, `.set`, `.mov_status`, `.pio_version`);
3. `.lang_opt sim <name> = <value>` lines, for what has no directive: the clock (`clock_hz`, or `clock_div` as a
   divider) and the pin mapping `in_base`, `jmp_pin`, `out_base`, `out_count`, `set_base`, `set_count`,
   `side_set_base`. They can also override the shift settings (`auto_pull`, `pull_threshold`,
   `shift_osr_right`, ...), the names are those of `pioemu.emulate()`;
4. the test, see below.

Dividers (`.clock_div`) refer to one system clock for the whole simulation, 150 MHz like the RP2350 of the
firmware (`SYS_CLOCK_HZ` in `config.py`, `KSO_SYS_CLOCK_HZ` to change it). A file that gives its clock more than
once (`.clock_div` and `clock_hz`, say) has to agree with itself, otherwise loading fails. The emulator has no
clock divider, the clock only turns PIO cycles into time.

Both `pio-parser` (`pio_file!`) and the C++ pioasm ignore `.lang_opt` lines, so a file that the firmware builds
can carry them, `hcs300_capture.pio` does:

```
.lang_opt sim clock_hz = 5000000
.lang_opt sim in_base = 0
.lang_opt sim jmp_pin = 0
```

`pio-parser` rejects the settings directives, so a file with them cannot go through `pio_file!`
(`hcs300_tx.pio` is one). To check what the firmware's assembler accepts:

```sh
cargo run --manifest-path tools/golden-gen/Cargo.toml -- --check ../../../sw/kso-fw-rs/pio/hcs300_capture.pio
```

The `.lang_opt sim clock_hz` of the capture program is a second copy of `calculate_pio_clock_divider(5_000_000)`
in `main.rs`, and nothing checks that they agree: change both together.

A file needs no clock and no pin mapping: for a program whose speed or pins are up to the user, like a PIO SPI,
the file says nothing and each test chooses. The `pio_program` fixture (`tests/conftest.py`) loads a file and
applies the settings of the test on top, with the same names as the `sim` options but as Python values:

```python
def test_spi_at_10_mhz(pio_program):
    sm = pio_program("spi.pio", clock_hz=10_000_000, out_base=3, set_base=4, side_set_base=5)
    ...

@pytest.mark.parametrize("clock_div", [3, 15, 150])
def test_spi_speeds(pio_program, clock_div):
    sm = pio_program("spi.pio", clock_div=clock_div)  # divider of the 150 MHz system clock
```

`SmProgram.configured(**overrides)` does the same on an already loaded program. Overrides add to the settings
of the file and a clock replaces the clock of the file. The result is immutable, so tests do not affect each
other. A module can shadow the fixtures to configure a program once for all its tests.

`pio_sim.harness.run()` runs any loaded program: input waveforms on GPIOs as (level, cycles) segments, TX words
up front, every RX push recorded (and taken out of the FIFO at once, like a fast CPU), every change of the
output pins recorded, `Trace.output_segments(pin)` turns them into a waveform. What a program needs as stimulus
and how its output is decoded belongs to the tests of that program, `src/pio_sim/hcs300_capture.py` is the example.

## What is tested

`tests/test_pio_files.py`: every `.pio` file in the firmware directory assembles and fits the 32 words, so a
new file with a mistake is caught even before it has tests.

`tests/test_config.py`, `tests/test_fixtures.py` and `tests/test_harness.py` check the layering of the settings,
the overrides of the tests and the runner with small inline programs.

`tests/test_hcs300_capture.py` drives `hcs300_capture.pio` with pin waveforms and checks what it pushes to the
RX FIFO. The timeout it pulls from the TX FIFO is chosen by the tests (`tests/conftest.py`), the sentinel
`0xFFFF_FFFF` is what the program pushes when its counter underflows. That the firmware's own timeout
(`HCS300_TIMEOUT_TICKS`) exceeds the longest header is a compile-time assert in `main.rs`.

- Pulse durations are exact within one tick (1 us) and unbiased on both edges, for random pulse widths at
  random phase against the PIO clock.
- Pulses far shorter than the shortest TE are all reported.
- A complete code word, generated by `test/system/hcs300_wf_gen.py` (the generator of the hardware test),
  is measured pulse by pulse at TE = 65, 100, 400 and 660 us.
- Back-to-back code words: idle marker between them if the guard time is longer than the timeout, none if not.
- An idle line produces exactly one sentinel, one timeout after the last edge, for two different timeouts.
- A stuck high line produces a sentinel and measurement resumes afterwards.

`tests/test_hcs300_tx.py` drives `hcs300_tx.pio`, the transmitter, with TX FIFO words and checks the waveform on
its pin (`src/pio_sim/hcs300_tx.py`). The expected waveform is made by `test/system/hcs300_wf_gen.py`, the
generator of the hardware test, and the time unit is the PIO cycle (one TE is two cycles):

- For several code words (all zeros, all ones, alternating, ...) and for each of the 16 button combinations the
  whole frame is identical to the generator's, pulse by pulse: preamble, header, 66 PWM bits, guard time.
  A code word (`Hcs300Codeword`) takes its buttons as `Button` flags (`Button.S1 | Button.S3`). They have the
  layout of the button status field of the datasheet (DS21137G figure 4-2) and of `Hcs300ButtonStatus` in
  `hcs300.rs`: S3 is bit 0, then S0, S1, S2. The field is sent LSb first, so on the air the order is S3, S0, S1,
  S2, and it is bits 31:28 of the second TX FIFO word. The generator numbers the buttons S0..S3 from bit 0,
  `Button.generator_value` converts.
- Back-to-back code words come out in order, 41.5 TE apart (the guard time of the generator plus the 2.5 TE
  the program needs to start the next frame), and nothing is sent without words.
- Fewer than a complete packet starts no frame, only the frame pin is driven, the pin can be chosen, and TE
  follows the clock divider (400 us at the `.clock_div 30000` of the file).

The program starts a frame when `txfifo < 2` is false: autopull moves the first word of a packet to the OSR as
soon as it arrives, so the status waits for the other two words. (With `txfifo < 3`, which the file had before,
three words never started a frame, a fourth word was needed.) The tests check that a packet of three words is
enough, that an incomplete next packet starts no frame, and that the settings of the file are the ones the
program needs: one OUT pin (`mov pins` drives the frame pin only), autopull at 32 bits, side-set with `opt`.

`tests/test_assembler.py` checks the small Python assembler (`src/pio_sim/assembler.py`) that turns the
`.pio` text into opcodes. pioemu has no assembler, and the existing Python ones need heavy dependencies
or the pico-sdk. The opcodes in `tests/golden_opcodes.json` come from the Rust `pio` assembler, the one
behind `pio_asm!`. Regenerate them after adding instruction forms to `tools/golden-gen/src/main.rs`:

```sh
cargo run --manifest-path tools/golden-gen/Cargo.toml > tests/golden_opcodes.json
```

The assembler handles every instruction and directive that `pio-parser` (behind `pio_asm!` and `pio_file!`) knows:
all instruction forms including irq and the RP2350 ones, delay and side-set, `.define` expressions, `.origin`,
`.side_set`, `.wrap_target` / `.wrap`, `public` labels, `.lang_opt`, `.program` and `% c-sdk { %}` blocks. The golden
file also holds wrap, origin, side-set settings and public defines of whole programs. What `pio-parser` rejects
is rejected here too with an `AssemblerError` naming the line, except for the settings directives of the C++
pioasm (`.clock_div`, `.fifo`, `.in`, `.out`, `.set`, `.mov_status`, `.pio_version`), which are read into
`Program` and turned into `pioemu.emulate()` arguments by `Program.emulator_options()`. `pio-parser` rejects those
directives, so `pio_file!` cannot build a program that has them. They follow the grammar in the pico-sdk's
`tools/pioasm/parser.yy` and are covered by unit tests only, there is no pioasm output to compare with.

## Limits

pioemu is a third-party emulator of the RP2040 PIO. The fixes in the fork were checked on a Pico 2, but the
emulator as a whole is not validated against silicon. The instructions the
firmware uses are the same on the RP2350. The GPIO input synchronizer is not modelled (a fixed latency on both
edges, it does not change measured durations), and the CPU is assumed to empty the RX FIFO instantly.
The decoder that turns the measured pulses into packets is Rust (`src/hcs300.rs`) and not covered here.
The stimulus of the hardware test is described in `test/system/README.md`.
