"""Behaviour of the HCS300 transmitter PIO program (hcs300_tx.pio), simulated on pioemu.

The program turns three TX FIFO words (the 66 data bits of a code word) into a frame on one pin. The expected
waveform is the one of `test/system/hcs300_wf_gen.py`, the generator of the hardware test. One TE is two PIO
cycles, so the tests count in cycles and the clock only matters for `test_te_follows_the_clock`.
"""

from dataclasses import replace

import pytest

from pio_sim.hcs300_tx import FRAME_TE, TE_CYCLES, Hcs300Codeword, Hcs300Tx
from pio_sim.waveforms import Button

CODEWORDS = {
    "typical": Hcs300Codeword(),
    "all zeros": Hcs300Codeword(0, 0, Button(0), vlow=False, repeat=False),
    "all ones": Hcs300Codeword(0xFFFF_FFFF, 0x0FFF_FFFF, Button.S0 | Button.S1 | Button.S2 | Button.S3, vlow=True, repeat=True),
    "alternating": Hcs300Codeword(0xAAAA_AAAA, 0x0555_5555, Button.S0 | Button.S2, vlow=True, repeat=False),
    "other": Hcs300Codeword(0x1234_5678, 0x0FED_CBA9, Button.S1 | Button.S2, vlow=False, repeat=True),
}

FRAME_CYCLES = FRAME_TE * TE_CYCLES
"""One frame including its 39 TE guard time"""

MAX_START_LATENCY_CYCLES = 10
"""The first pulse comes within this many cycles of the start (startup instructions, status check, setup)"""


def lead_of(waveform) -> int:
    """Low cycles before the first pulse"""
    level, cycles = waveform[0]
    assert level == 0
    return cycles


def frame_starts(waveform) -> list[int]:
    """Cycle of the first preamble pulse of every frame: the first rising edge, and every rising edge after a
    low period longer than the header (10 TE)"""
    starts, cycle, level, low_run = [], 0, 0, 0
    for new_level, cycles in waveform:
        if new_level and not level and (not starts or low_run > 10 * TE_CYCLES):
            starts.append(cycle)
        low_run = low_run + cycles if not new_level else 0
        level = new_level
        cycle += cycles
    return starts


def test_program_fits_in_pio_instruction_memory(hcs300_tx):
    assert len(hcs300_tx.sm.program.code) <= 32


def assert_frame_matches_the_generator(hcs300_tx, codeword):
    """Every pulse of the frame, from the first preamble pulse to the end of the guard time"""
    trace = hcs300_tx.transmit([codeword], cycles=MAX_START_LATENCY_CYCLES + FRAME_CYCLES)
    waveform = hcs300_tx.waveform(trace)
    lead = lead_of(waveform)

    # the run ends where the guard time ends, so the last pulse needs the lead to be known
    trace = hcs300_tx.transmit([codeword], cycles=lead + FRAME_CYCLES)

    assert lead <= MAX_START_LATENCY_CYCLES
    assert hcs300_tx.waveform(trace) == hcs300_tx.expected_waveform([codeword], lead)


@pytest.mark.parametrize("codeword", CODEWORDS.values(), ids=CODEWORDS.keys())
def test_frame_matches_the_generator(hcs300_tx, codeword):
    assert_frame_matches_the_generator(hcs300_tx, codeword)


@pytest.mark.parametrize("buttons", list(map(Button, range(16))), ids=lambda buttons: buttons.label)
def test_every_button_combination_is_sent(hcs300_tx, buttons):
    assert_frame_matches_the_generator(hcs300_tx, Hcs300Codeword(buttons=buttons))


def test_buttons_are_sent_in_the_order_s3_s0_s1_s2():
    """DS21137G figure 4-2: the button status field is S2 S1 S0 S3 from MSb to LSb, sent LSb first. The field
    is data bits 60..63, which are bits 28..31 of the second TX FIFO word."""
    on_the_air = (Button.S3, Button.S0, Button.S1, Button.S2)

    for position, button in enumerate(on_the_air):
        assert Hcs300Codeword(buttons=button).words()[1] >> 28 == 1 << position, button.label


@pytest.mark.parametrize("buttons", list(map(Button, range(16))), ids=lambda buttons: buttons.label)
def test_the_second_word_holds_the_button_status_field_in_its_top_bits(buttons):
    """So the firmware can shift `Hcs300ButtonStatus` into bits 31:28 as it is"""
    word = Hcs300Codeword(buttons=buttons).words()[1]

    assert word >> 28 == int(buttons)
    assert word & 0x0FFF_FFFF == Hcs300Codeword().serial


def test_button_layouts():
    """Datasheet and Rust: S3 is bit 0 ... S2 is bit 3. The generator numbers them S0 ... S3 from bit 0."""
    assert [int(button) for button in (Button.S3, Button.S0, Button.S1, Button.S2)] == [1, 2, 4, 8]
    assert [button.generator_value for button in (Button.S0, Button.S1, Button.S2, Button.S3)] == [1, 2, 4, 8]
    assert (Button.S3 | Button.S1).generator_value == 0b1010
    assert sorted(buttons.generator_value for buttons in map(Button, range(16))) == list(range(16))


def test_codeword_converts_and_checks_its_values():
    codeword = Hcs300Codeword(buttons=0b0101, vlow=1, repeat=0)

    assert codeword.buttons == Button.S3 | Button.S1
    assert isinstance(codeword.buttons, Button)
    assert codeword.button == 0b0101
    assert (codeword.vlow, codeword.repeat) == (True, False)
    assert codeword.fields() == {"encrypted": 0xA5C3_1E96, "serial": 0x0ABC_DEF1, "button": 0b1010, "vlow": 1, "repeat": 0}
    with pytest.raises(ValueError):
        Hcs300Codeword(buttons=0b1_0000)


def test_code_words_follow_each_other_in_order_with_the_guard_time(hcs300_tx):
    first, second = CODEWORDS["typical"], CODEWORDS["other"]
    lead = lead_of(hcs300_tx.waveform(hcs300_tx.transmit([first], cycles=MAX_START_LATENCY_CYCLES + 20)))

    trace = hcs300_tx.transmit([first, second], cycles=lead + 5 + 2 * FRAME_CYCLES)

    waveform = hcs300_tx.waveform(trace)
    assert waveform == hcs300_tx.expected_waveform([first, second], lead)
    first_start, second_start = frame_starts(waveform)
    # 231 TE up to the end of the last bit, then 39 TE of guard time and 2.5 TE until the next preamble
    assert second_start - first_start == (231 + 39) * TE_CYCLES + 5
    assert (second_start - first_start) / TE_CYCLES == FRAME_TE + 2.5


def test_idle_after_the_last_frame(hcs300_tx):
    """Without more words the program waits with the pin low and sends nothing more"""
    codeword = CODEWORDS["typical"]

    trace = hcs300_tx.transmit([codeword], cycles=4 * FRAME_CYCLES)

    waveform = hcs300_tx.waveform(trace)
    assert len(frame_starts(waveform)) == 1
    assert waveform[-1][0] == 0
    assert waveform[-1][1] > 3 * FRAME_CYCLES  # the guard time and the idle wait are one low period


@pytest.mark.parametrize("words", [0, 1, 2], ids=lambda words: f"{words} words")
def test_no_frame_without_a_complete_packet(hcs300_tx, words):
    trace = hcs300_tx.simulate(CODEWORDS["typical"].words()[:words], cycles=2 * FRAME_CYCLES)

    assert hcs300_tx.waveform(trace) == [(0, 2 * FRAME_CYCLES)]


def test_only_the_frame_pin_is_driven(hcs300_tx):
    trace = hcs300_tx.transmit([CODEWORDS["typical"]], cycles=FRAME_CYCLES)

    assert {change.values for change in trace.pin_changes} == {0, 1 << hcs300_tx.pin}


def test_frame_pin_can_be_chosen(hcs300_tx):
    on_gpio_5 = Hcs300Tx(hcs300_tx.sm.configured(out_base=5, side_set_base=5))
    cycles = MAX_START_LATENCY_CYCLES + FRAME_CYCLES

    trace = on_gpio_5.transmit([CODEWORDS["typical"]], cycles=cycles)

    assert on_gpio_5.pin == 5
    assert {change.values for change in trace.pin_changes} == {0, 1 << 5}
    assert on_gpio_5.waveform(trace) == hcs300_tx.waveform(hcs300_tx.transmit([CODEWORDS["typical"]], cycles=cycles))


@pytest.mark.parametrize("clock_div, te_us", [(30_000, 400), (15_000, 200), (7_500, 100)])
def test_te_follows_the_clock(hcs300_tx, clock_div, te_us):
    """The program counts cycles: TE is two of them, 400 us at the `.clock_div 30000` of the file (150 MHz)"""
    tx = replace(hcs300_tx, sm=hcs300_tx.sm.configured(clock_div=clock_div))

    first_pulse_cycles = tx.waveform(tx.transmit([CODEWORDS["typical"]], cycles=30))[1][1]

    assert tx.te_us == pytest.approx(te_us)
    assert first_pulse_cycles / tx.sm.config.pio_hz * 1e6 == pytest.approx(te_us)  # the first preamble pulse


def test_a_single_packet_of_three_words_is_transmitted(hcs300_tx):
    """Autopull moves the first word to the OSR, so `txfifo < 2` waits for the other two: three words are enough"""
    codeword = CODEWORDS["typical"]

    waveform = hcs300_tx.waveform(hcs300_tx.transmit([codeword], cycles=MAX_START_LATENCY_CYCLES + FRAME_CYCLES))
    lead = lead_of(waveform)

    waveform = hcs300_tx.waveform(hcs300_tx.transmit([codeword], cycles=lead + FRAME_CYCLES))
    assert waveform == hcs300_tx.expected_waveform([codeword], lead)


def test_an_incomplete_next_packet_does_not_start_a_frame(hcs300_tx):
    """The first word of the next packet is in the OSR and the second in the FIFO: `txfifo < 2` still holds"""
    first, second = CODEWORDS["typical"], CODEWORDS["other"]
    words = first.words() + second.words()[:2]

    trace = hcs300_tx.simulate(words, cycles=3 * FRAME_CYCLES)

    waveform = hcs300_tx.waveform(trace)
    assert len(frame_starts(waveform)) == 1


def test_the_settings_of_the_file(hcs300_tx):
    """What the program needs from the state machine configuration is in the file, as the C SDK would use it"""
    options = hcs300_tx.sm.config.options

    assert options["out_count"] == 1  # `mov pins` drives the frame pin only
    assert options["status_n"] == 2 and options["status_sel"] == 0  # txfifo < 2
    assert (options["auto_pull"], options["pull_threshold"], options["shift_osr_right"]) == (True, 32, True)
    assert (options["side_set_count"], options["side_set_opt"]) == (1, True)
    assert hcs300_tx.sm.config.pio_hz == 5_000  # 150 MHz / 30000
