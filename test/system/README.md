# HCS300 stimulus for the system test

`hcs300_wf_gen.py` generates an HCS300 code word as a CSV for the Pattern Generator of a Digilent Analog
Discovery (WaveForms). The Analog Discovery drives the HCS300 input of the firmware, GPIO 8 (`PIN_8`) of the
RP2350, so the PIO measurement and the decoder can be tested without a real transmitter.

Python 3, no dependencies. The PIO simulation tests in `test/sim/pio` use the same generator.

| File | Purpose |
|---|---|
| `hcs300_wf_gen.py` | Waveform generator |
| `output.csv` | Generated waveform, 40 kHz variant below |
| `hcs300.dwf3work` | WaveForms workspace (Patterns + Logic). It stores a copy of the imported data, so import `output.csv` again after regenerating it |

## Generate

```sh
python hcs300_wf_gen.py --encrypted 0xDEADBEEF --serial 0x1234567 --button 0x5 --te 400 --sample_count 8192 --period 204800 -o output.csv
```

| | |
|---|---|
| Sample time | 25 us, so the pattern frequency is **40 kHz** (100 MHz / 2500, an exact divider) |
| TE | 400 us = 16 samples |
| Code word | 270 TE with the 39 TE guard time = 4320 samples = 108 ms |
| Rest of the buffer | 3872 samples idle low, 8192 samples in total |
| Pattern period | 204.8 ms: one code word, then 112.8 ms low (last bit + guard + idle) |
| Payload | encrypted `0xDEADBEEF`, serial `0x1234567`, buttons S0 + S2 (`0x5`), vlow 0, repeat 0 |

Add `-v` to print the summary above and the frequency to enter in WaveForms. To choose other parameters:

- TE is a whole number of samples, the sample frequency is 100 MHz divided by an integer.
- `sample_count` is at least 270 x TE samples (the generator refuses otherwise) and fits the device buffer.
- `period = sample_count / frequency`.

## WaveForms (Analog Discovery, Patterns)

Settings of the saved workspace, `hcs300.dwf3work`:

- Channel **DIO 1**, as in the CSV header.
- Type **Custom**, Frequency **40 kHz**.
- Run **200 ms**, Repeat infinite.
- Output: the workspace uses Three-State. Push-Pull always drives the line, which is the safer choice because
  the firmware input has no pull resistor.
- Import `output.csv`. WaveForms does not accept more than 9999 in the sample count field, 8192 fits.

Check the imported pattern in the editor: the first 16 samples are high, the next 16 low.

Checked on 2026-10-27: a logic analyzer shows the correct waveform on the pin, and the firmware decodes it
correctly on the target.

## The stored pattern is not the pin signal

The Patterns data in `hcs300.dwf3work` is stored as 32768 samples: `output.csv` with three zeros after every
sample (8192 x 4), so every group of four is `1000` or `0000`. Taken literally, that would be 1-sample spikes
at 4x the time scale. The logic analyzer shows the correct waveform on the pin, so this stored form is not the
pin signal. It is not known whether WaveForms keeps the data that way internally or the saved file differs from
the live editor state. Do not judge the output from the stored buffer, look at the pin: the Logic analyzer, or
the firmware log below.

## Check on the target

Connect DIO 1 to GPIO 8 and the grounds together. The RTT log shows one line per code word:

```
HCS300: serial 01234567, buttons 1010, vlow false, repeat false, encrypted deadbeef, TE 400 us
```

`buttons` is the decoder's mask in transmission order (S3, S0, S1, S2 as bits 0 to 3), so S0 and S2 pressed
shows as `1010`. TE is measured from the preamble and should be within a microsecond or two of 400.
