#!/usr/bin/env python3
"""
HCS300 KeeLoq Waveform Generator for Digilent WaveForms Pattern Output

Generates HCS300 code hopping encoder waveforms and exports to CSV format
compatible with Digilent WaveForms software pattern output.

HCS300 Transmission Format (66 bits total, DS21137G Fig. 4-1/9-3/9-4, Table 9-4):
- Preamble: 23 Te, 50% duty cycle (12 Te high, 11 Te low, starts and ends high)
- Header: 10 Te low
- Data (66 bits PWM encoded, each field LSB first):
  - 32-bit encrypted portion
  - 28-bit serial number
  - 4-bit button status, transmitted in the order S3, S0, S1, S2
  - 1-bit Vlow (low voltage indicator)
  - 1-bit Repeat

PWM Encoding:
- Bit "0": 2*Te high, Te low (3*Te total)
- Bit "1": Te high, 2*Te low (3*Te total)
- Guard time: 39*Te low after last bit

Total frame: 23 + 10 + 66*3 + 39 = 270 Te.

WaveForms: the CSV holds exactly one period (--period) of --sample_count samples.
Set the custom pattern Frequency (sample update frequency) to sample_count / period
= 1e6 / sample_time_us Hz; the pattern then repeats every --period.
"""

import argparse
import sys
from datetime import datetime
from typing import List, Tuple


def validate_inputs(
    encrypted: int,
    serial: int,
    button: int,
    vlow: int,
    repeat: int,
    te_us: float,
    sample_count: int,
    period_us: float,
    max_error_pct: float,
) -> Tuple[bool, str]:
    """Validate all input parameters."""
    errors = []

    if encrypted < 0 or encrypted > 0xFFFFFFFF:
        errors.append(f"Encrypted part must be 32-bit (0-0xFFFFFFFF), got: 0x{encrypted:X}")

    if serial < 0 or serial > 0x0FFFFFFF:
        errors.append(f"Serial must be 28-bit (0-0x0FFFFFFF), got: 0x{serial:X}")

    if button < 0 or button > 0x0F:
        errors.append(f"Button status must be 4-bit (0-0x0F), got: 0x{button:X}")

    if vlow not in (0, 1):
        errors.append(f"Vlow must be 0 or 1, got: {vlow}")

    if repeat not in (0, 1):
        errors.append(f"Repeat must be 0 or 1, got: {repeat}")

    if te_us <= 0:
        errors.append(f"Te must be positive, got: {te_us}")

    if sample_count <= 0:
        errors.append(f"Sample count must be positive, got: {sample_count}")

    if period_us <= 0:
        errors.append(f"Period must be positive, got: {period_us}")

    if max_error_pct <= 0 or max_error_pct >= 100:
        errors.append(f"Max error percentage must be between 0 and 100, got: {max_error_pct}")

    if errors:
        return False, "\n".join(errors)

    # Check resolution constraint
    sample_time_us = period_us / sample_count
    te_samples = te_us / sample_time_us
    te_samples_rounded = round(te_samples)

    if te_samples_rounded == 0:
        return False, f"Te ({te_us} us) is too small for the given resolution ({sample_time_us} us/sample)"

    te_real = te_samples_rounded * sample_time_us
    te_error_pct = abs(te_real - te_us) / te_us * 100

    if te_error_pct > max_error_pct:
        return False, (
            f"Te resolution error ({te_error_pct:.2f}%) exceeds maximum allowed ({max_error_pct}%).\n"
            f"Te nominal: {te_us} us, Te real: {te_real:.3f} us\n"
            f"Consider increasing sample_count or adjusting period."
        )

    frame_samples = calculate_waveform_duration_te() * te_samples_rounded
    if frame_samples > sample_count:
        return False, (
            f"Frame needs {frame_samples} samples ({calculate_waveform_duration_te()} Te * {te_samples_rounded}) "
            f"but sample_count is {sample_count}; the waveform would be truncated.\n"
            f"Increase period to at least {frame_samples * sample_time_us:.0f} us "
            f"or increase sample_count."
        )

    return True, f"Te nominal: {te_us} us, Te real: {te_real:.3f} us, Error: {te_error_pct:.2f}%"


def calculate_waveform_duration_te(include_guard: bool = True) -> int:
    """
    Calculate total waveform duration in Te units.

    Preamble: 23*Te (alternating Te high / Te low, starts and ends high)
    Header: 10*Te low
    Data: 66 bits * 3*Te = 198*Te
    Guard: 39*Te

    Total with guard: 23 + 10 + 198 + 39 = 270*Te
    Total without guard: 23 + 10 + 198 = 231*Te
    """
    preamble_te = 23  # 23 alternating Te segments (12 high, 11 low)
    header_te = 10  # 10*Te low
    data_te = 66 * 3  # 66 bits, 3*Te each
    guard_te = 39 if include_guard else 0

    return preamble_te + header_te + data_te + guard_te


def build_data_bits(encrypted: int, serial: int, button: int, vlow: int, repeat: int) -> List[int]:
    """
    Build the 66-bit data sequence (LSB first for each field).

    Order: encrypted (32), serial (28), button (4: S3,S0,S1,S2), vlow (1), repeat (1)
    """
    bits = []

    # 32-bit encrypted (LSB first)
    for i in range(32):
        bits.append((encrypted >> i) & 1)

    # 28-bit serial (LSB first)
    for i in range(28):
        bits.append((serial >> i) & 1)

    # 4-bit button status: bit i of `button` is S<i>; transmitted order is S3, S0, S1, S2
    for s in (3, 0, 1, 2):
        bits.append((button >> s) & 1)

    # 1-bit vlow
    bits.append(vlow)

    # 1-bit repeat
    bits.append(repeat)

    return bits


def generate_waveform(
    encrypted: int,
    serial: int,
    button: int,
    vlow: int,
    repeat: int,
    te_us: float,
    sample_count: int,
    period_us: float,
) -> List[str]:
    """
    Generate the HCS300 waveform as a list of sample values.

    Returns list of '0', '1', or 'Z' strings.
    """
    sample_time_us = period_us / sample_count
    te_samples = round(te_us / sample_time_us)

    # Build data bits
    data_bits = build_data_bits(encrypted, serial, button, vlow, repeat)

    # Generate waveform segments
    waveform = []

    # Preamble: 23 pulses of Te (alternating high/low), starts high, ends high
    # Total: 12 Te high, 11 Te low
    for i in range(23):
        if i % 2 == 0:  # Even indices: high
            waveform.extend(['1'] * te_samples)
        else:  # Odd indices: low
            waveform.extend(['0'] * te_samples)

    # Header: 10*Te low
    waveform.extend(['0'] * (10 * te_samples))

    # Data bits (PWM encoded)
    for bit in data_bits:
        if bit == 0:
            # Logic 0: 2*Te high, Te low
            waveform.extend(['1'] * (2 * te_samples))
            waveform.extend(['0'] * te_samples)
        else:
            # Logic 1: Te high, 2*Te low
            waveform.extend(['1'] * te_samples)
            waveform.extend(['0'] * (2 * te_samples))

    # Guard time: 39*Te low
    waveform.extend(['0'] * (39 * te_samples))

    # Pad or truncate to match sample_count
    waveform_len = len(waveform)

    if waveform_len < sample_count:
        # Pad with '0' (idle low)
        waveform.extend(['0'] * (sample_count - waveform_len))
    elif waveform_len > sample_count:
        # Truncate (with warning)
        print(
            f"Warning: Waveform ({waveform_len} samples) exceeds sample_count ({sample_count}). Truncating.",
            file=sys.stderr,
        )
        waveform = waveform[:sample_count]

    return waveform


def export_csv(
    waveform: List[str],
    output_file: str,
    device_name: str = "Discovery",
    serial_number: str = "SN:210244546264",
    dio_channel: int = 1,
) -> None:
    """Export waveform to Digilent WaveForms compatible CSV format."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    with open(output_file, 'w', newline='\n') as f:
        # Write header
        f.write(f"#Digilent WaveForms Patterns DIO {dio_channel} data\n")
        f.write(f"#Device Name: {device_name}\n")
        f.write(f"#Serial Number: {serial_number}\n")
        f.write(f"#Date Time: {timestamp}\n")
        f.write("\n")
        f.write(f"DIO {dio_channel}\n")

        # Write samples
        for sample in waveform:
            f.write(f"{sample}\n")


def parse_int(value: str) -> int:
    """Parse integer from string, supporting hex (0x) and binary (0b) prefixes."""
    value = value.strip()
    if value.lower().startswith('0x'):
        return int(value, 16)
    elif value.lower().startswith('0b'):
        return int(value, 2)
    else:
        return int(value)


def main():
    parser = argparse.ArgumentParser(
        description="Generate HCS300 KeeLoq waveform for Digilent WaveForms Pattern Output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --encrypted 0xDEADBEEF --serial 0x1234567 --button 0x5 --te 400 --sample_count 8192 --period 120000 -o output.csv
  %(prog)s -e 0xABCDEF12 -s 0x0FEDCBA -b 3 --vlow 1 --repeat 0 --te 400 --sample_count 16384 --period 200000 -o waveform.csv

Integer inputs support decimal, hex (0x prefix), and binary (0b prefix) formats.
        """,
    )

    parser.add_argument(
        '-e', '--encrypted',
        type=parse_int,
        required=True,
        help='32-bit encrypted part (hex: 0x..., binary: 0b..., or decimal)',
    )
    parser.add_argument(
        '-s', '--serial',
        type=parse_int,
        required=True,
        help='28-bit serial number (hex: 0x..., binary: 0b..., or decimal)',
    )
    parser.add_argument(
        '-b', '--button',
        type=parse_int,
        required=True,
        help='4-bit button status (hex: 0x..., binary: 0b..., or decimal)',
    )
    parser.add_argument(
        '--vlow',
        type=int,
        default=0,
        choices=[0, 1],
        help='1-bit low voltage indicator (default: 0)',
    )
    parser.add_argument(
        '--repeat',
        type=int,
        default=0,
        choices=[0, 1],
        help='1-bit repeat flag (default: 0)',
    )
    parser.add_argument(
        '--te',
        type=float,
        required=True,
        help='Basic pulse element Te in microseconds (HCS300 typical: 400us)',
    )
    parser.add_argument(
        '--sample_count',
        type=int,
        required=True,
        help='Number of samples to generate',
    )
    parser.add_argument(
        '--period',
        type=float,
        required=True,
        help='Total waveform period in microseconds',
    )
    parser.add_argument(
        '--max_error_pct',
        type=float,
        default=5.0,
        help='Maximum allowed Te resolution error in percent (default: 5.0)',
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        required=True,
        help='Output CSV file path',
    )
    parser.add_argument(
        '--device_name',
        type=str,
        default='Discovery',
        help='Device name for CSV header (default: Discovery)',
    )
    parser.add_argument(
        '--serial_number',
        type=str,
        default='SN:210244546264',
        help='Serial number for CSV header (default: SN:210244546264)',
    )
    parser.add_argument(
        '--dio',
        type=int,
        default=1,
        help='DIO channel number (default: 1)',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output',
    )

    args = parser.parse_args()

    # Validate inputs
    valid, message = validate_inputs(
        args.encrypted,
        args.serial,
        args.button,
        args.vlow,
        args.repeat,
        args.te,
        args.sample_count,
        args.period,
        args.max_error_pct,
    )

    if not valid:
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Validation passed: {message}")
        print(f"Encrypted: 0x{args.encrypted:08X}")
        print(f"Serial: 0x{args.serial:07X}")
        print(f"Button: 0x{args.button:X}")
        print(f"Vlow: {args.vlow}")
        print(f"Repeat: {args.repeat}")

        # Calculate expected waveform duration
        sample_time_us = args.period / args.sample_count
        te_samples = round(args.te / sample_time_us)
        waveform_duration_te = calculate_waveform_duration_te()
        waveform_duration_samples = waveform_duration_te * te_samples
        waveform_duration_us = waveform_duration_samples * sample_time_us

        print(f"WaveForms custom pattern Frequency: {1e6 / sample_time_us:.6g} Hz (pattern repeats every {args.period:.6g} us)")
        print(f"Sample time: {sample_time_us:.3f} us")
        print(f"Te in samples: {te_samples}")
        print(f"Waveform duration: {waveform_duration_te} Te = {waveform_duration_us:.1f} us = {waveform_duration_samples} samples")

    # Generate waveform
    waveform = generate_waveform(
        args.encrypted,
        args.serial,
        args.button,
        args.vlow,
        args.repeat,
        args.te,
        args.sample_count,
        args.period,
    )

    # Export to CSV
    export_csv(
        waveform,
        args.output,
        device_name=args.device_name,
        serial_number=args.serial_number,
        dio_channel=args.dio,
    )

    if args.verbose:
        print(f"Waveform exported to: {args.output}")
        print(f"Total samples: {len(waveform)}")

    print(f"Successfully generated {args.output}")


if __name__ == '__main__':
    main()
