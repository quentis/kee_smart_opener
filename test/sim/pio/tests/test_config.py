"""Where the state machine settings come from: pioemu defaults < program text < `.lang_opt sim` lines < the test."""

import pytest

from pio_sim.assembler import assemble
from pio_sim.config import SYS_CLOCK_HZ, ConfigError, build_config


def config(source: str, **kwargs):
    return build_config(assemble(source + "\nnop"), **kwargs)


def test_nothing_given_leaves_only_the_wrap_and_no_clock():
    result = config("")

    assert result.options == {"wrap_target": 0, "wrap_top": 0}
    assert result.pio_hz is None
    with pytest.raises(ConfigError):
        result.cycles_per_us


def test_settings_directives_of_the_program_text_are_used():
    result = config(".side_set 1 opt\n.out 32 left auto 16\n.in 8 right auto 4\n.set 2\n.mov_status rxfifo < 2")

    assert result.options == {
        "wrap_target": 0,
        "wrap_top": 0,
        "side_set_count": 1,
        "side_set_opt": True,
        "auto_pull": True,
        "pull_threshold": 16,
        "shift_osr_right": False,
        "out_count": 32,
        "auto_push": True,
        "push_threshold": 4,
        "shift_isr_right": True,
        "set_count": 2,
        "status_sel": 1,
        "status_n": 2,
    }


def test_sim_lang_opts_add_what_has_no_directive():
    result = config(
        ".lang_opt sim in_base = 4\n.lang_opt sim jmp_pin = 0x10\n.lang_opt sim out_base = 2\n"
        ".lang_opt sim set_base = 1\n.lang_opt sim side_set_base = 7\n.lang_opt sim shift_isr_right = false"
    )

    assert result.options == {
        "wrap_target": 0,
        "wrap_top": 0,
        "in_base": 4,
        "jmp_pin": 16,
        "out_base": 2,
        "set_base": 1,
        "side_set_base": 7,
        "shift_isr_right": False,
    }


def test_sim_lang_opts_override_the_directives():
    result = config(".out 32 right auto 32\n.lang_opt sim pull_threshold = 16\n.lang_opt sim auto_pull = false")

    assert result.options["pull_threshold"] == 16
    assert result.options["auto_pull"] is False
    assert result.options["shift_osr_right"] is True  # from the directive


def test_lang_opts_of_other_languages_are_ignored():
    result = config(".lang_opt python sideset_init = pico.PIO.OUT_LOW\n.lang_opt rust whatever = 1")

    assert result.options == {"wrap_target": 0, "wrap_top": 0}


def test_clock_hz_gives_the_pio_clock():
    result = config(".lang_opt sim clock_hz = 5000000")

    assert result.pio_hz == 5_000_000
    assert result.cycles_per_us == 5


def test_clock_div_directive_divides_the_system_clock():
    assert config(".clock_div 30").pio_hz == SYS_CLOCK_HZ / 30
    assert config(".clock_div 1.5").pio_hz == SYS_CLOCK_HZ / 1.5
    assert config(".clock_div 30", sys_clock_hz=125_000_000).pio_hz == 125_000_000 / 30


def test_clock_div_lang_opt_divides_the_system_clock():
    assert config(".lang_opt sim clock_div = 30").pio_hz == SYS_CLOCK_HZ / 30
    assert config(".lang_opt sim clock_div = 12.5").pio_hz == SYS_CLOCK_HZ / 12.5


def test_the_clock_may_be_given_more_than_once_if_it_is_consistent():
    result = config(".clock_div 30\n.lang_opt sim clock_hz = 5000000\n.lang_opt sim clock_div = 30")

    assert result.pio_hz == 5_000_000


@pytest.mark.parametrize(
    "source",
    [
        ".clock_div 30000\n.lang_opt sim clock_hz = 2000000",
        ".clock_div 30\n.lang_opt sim clock_div = 31",
        ".lang_opt sim clock_hz = 5000000\n.lang_opt sim clock_div = 31",
    ],
)
def test_a_clock_given_twice_with_different_values_is_an_error(source):
    with pytest.raises(ConfigError, match="differ"):
        config(source)


def test_a_clock_that_is_not_whole_megahertz_has_no_cycles_per_us():
    result = config(".clock_div 30000")

    assert result.pio_hz == 5_000
    with pytest.raises(ConfigError):
        result.cycles_per_us


@pytest.mark.parametrize(
    "line",
    [
        ".lang_opt sim bogus = 1",
        ".lang_opt sim sys_clock_hz = 125000000",  # one system clock for the whole simulation
        ".lang_opt sim in_base = pin0",
        ".lang_opt sim auto_pull = maybe",
        ".lang_opt sim clock_hz = fast",
        ".lang_opt sim clock_hz = 0",
        ".lang_opt sim clock_div = -1",
        ".lang_opt sim wrap_top = 3",  # comes from .wrap
        ".lang_opt sim side_set_count = 1",  # comes from .side_set
    ],
)
def test_bad_sim_lang_opts_are_rejected(line):
    with pytest.raises(ConfigError):
        config(line)


# --- overrides of the test ---


def test_overrides_add_to_the_settings_of_the_file():
    base = config(".out 32 left auto 16\n.lang_opt sim out_base = 2\n.lang_opt sim clock_hz = 5000000")

    result = base.with_overrides(out_base=5, set_base=1, auto_pull=False)

    assert result.options["out_base"] == 5  # replaced
    assert result.options["set_base"] == 1  # added
    assert result.options["auto_pull"] is False
    assert result.options["pull_threshold"] == 16  # untouched
    assert result.options["shift_osr_right"] is False
    assert result.pio_hz == 5_000_000
    assert base.options["out_base"] == 2  # the original is not changed


def test_override_clock_hz_and_clock_div_replace_the_clock_of_the_file():
    base = config(".lang_opt sim clock_hz = 5000000")

    assert base.with_overrides(clock_hz=10_000_000).pio_hz == 10_000_000
    assert base.with_overrides(clock_div=15).pio_hz == SYS_CLOCK_HZ / 15
    assert config("").with_overrides(clock_hz=1_000_000).cycles_per_us == 1


def test_override_clock_div_refers_to_the_system_clock_of_the_config():
    result = config("", sys_clock_hz=125_000_000).with_overrides(clock_div=12.5)

    assert result.pio_hz == 10_000_000


@pytest.mark.parametrize(
    "overrides",
    [
        {"bogus": 1},
        {"in_base": "3"},
        {"in_base": True},
        {"in_base": 1.5},
        {"auto_pull": 1},
        {"clock_hz": 0},
        {"clock_hz": "fast"},
        {"clock_div": -2},
        {"clock_hz": 1_000_000, "clock_div": 5},
        {"wrap_top": 3},
        {"sys_clock_hz": 125_000_000},
    ],
)
def test_bad_overrides_are_rejected(overrides):
    with pytest.raises(ConfigError):
        config("").with_overrides(**overrides)
