//! # HCS300 Protocol Driver
//!
//! Provides encoding, decoding, and timing definitions for KeeLoq HCS300
//! transmission packets in `#![no_std]` environments.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Hcs300ButtonStatus(u8);

/// Button status representation for HCS300
impl Hcs300ButtonStatus {
    /// Bits of the 4-bit button field
    pub const MASK: u8 = 0x0F;

    /// Button S0 mask
    pub const S0: u8 = 1 << 1;

    /// Button S1 mask
    pub const S1: u8 = 1 << 2;

    /// Button S2 mask
    pub const S2: u8 = 1 << 3;

    /// Button S3 mask
    pub const S3: u8 = 1 << 0;

    /// Returns `None` if `value` has bits set outside the 4-bit button field
    pub const fn new(value: u8) -> Option<Self> {
        if value & !Self::MASK == 0 {
            Some(Self(value))
        } else {
            None
        }
    }

    pub const fn get(&self) -> u8 {
        self.0
    }

    /// Returns true if S0 is pressed
    #[inline(always)]
    pub const fn s0(&self) -> bool {
        (self.0 & Self::S0) != 0
    }

    /// Returns true if S1 is pressed
    #[inline(always)]
    pub const fn s1(&self) -> bool {
        (self.0 & Self::S1) != 0
    }

    /// Returns true if S2 is pressed
    #[inline(always)]
    pub const fn s2(&self) -> bool {
        (self.0 & Self::S2) != 0
    }

    /// Returns true if S3 is pressed
    #[inline(always)]
    pub const fn s3(&self) -> bool {
        (self.0 & Self::S3) != 0
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Hcs300SerialNumber(u32);

impl Hcs300SerialNumber {
    pub const BITS: u32 = 28;
    pub const MASK: u32 = (1 << Self::BITS) - 1;

    pub const fn new(value: u32) -> Option<Self> {
        if value <= Self::MASK {
            Some(Self(value))
        } else {
            None
        }
    }

    pub const fn get(&self) -> u32 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Hcs300EncodeError {
    /// Provided buffer is smaller than [`Hcs300Packet::CODEWORD_BYTES`].
    BufferTooSmall { required: usize, actual: usize },
}

/// Represents an unencoded HCS300 packet payload.
///
/// Contains the decrypted transmission data, hardware status flags,
/// and the pre-computed encrypted hopping code portion.
///
/// All HCS300 timings values are integer multiples of TE.
/// TE is configurable between: 100us, 200us, 400us.
///
/// Keeloq HCS300 packet (code word):
///   - Preamble: 23 TE (12 sync pulses) - 50% duty cycle
///   - Header: 10 TE gap
///   - Data: 66 bits -> 1 bit is 3 TE (PWM modulated)
///     - Encrypted portion: 32 bit
///     - Fix portion: 32 bit
///         - Serial number: 18 bit
///         - Button code: 4 bit
///         - Vlow: 1 bit
///         - RPT: 1 bit
///     - 1 bit:
///         - 0 bit: 2 TE high, 1 TE low
///         - 1 bit: 1 TE high, 2 TE low
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Hcs300Packet {
    /// 28-bit factory-assigned transmitter serial number.
    pub serial_number: Hcs300SerialNumber,

    /// 4-bit active button combination mask (`S0`..`S3`).
    pub button_status: Hcs300ButtonStatus,

    /// Low battery voltage flag.
    ///
    /// Set to `true` when the transmitter supply drops below ~2.2V.
    pub vlow: bool,

    /// RPT: Repeat indicator
    ///
    /// This bit will be low for the first transmitted word. If a button is held down for more than
    /// one transmitted code word, this bit will be set to indicate a repeated code word and remain
    /// set until the button is released.
    pub repeat: bool,

    /// 32-bit encrypted hopping-code payload containing the sync counter.
    pub encrypted: u32,
}

impl Hcs300Packet {
    /// Preamble (50% duty cycle) length in TE
    pub const PREAMBLE_TE: usize = 23;

    /// Gap between preamble and data
    pub const HEADER_GAP_TE: usize = 10;

    /// Fixed portion of code word data
    pub const FIXED_BITS: usize = 34;

    /// Encrypted portion of code word data
    pub const ENCRYPTED_BITS: usize = 32;

    /// Data bit length in TE
    pub const BIT_TE: usize = 3;

    /// Data portion bit count (66 bits)
    pub const DATA_BITS: usize = Self::ENCRYPTED_BITS + Self::FIXED_BITS;

    /// Data portion length in TE (each bit is encoded in 3 TE - PWM modulated)
    pub const DATA_BITS_TE: usize = Self::DATA_BITS * Self::BIT_TE;

    /// Code word length in TE (preamble + header gap + data portion)
    pub const CODEWORD_TE: usize = (Self::PREAMBLE_TE + Self::HEADER_GAP_TE + Self::DATA_BITS_TE);

    /// Code word data length in bytes
    pub const CODEWORD_DATA_BYTES: usize = Self::DATA_BITS_TE.div_ceil(8);

    // Code word length in bytes
    pub const CODEWORD_BYTES: usize =
        (Self::PREAMBLE_TE + Self::HEADER_GAP_TE + Self::DATA_BITS_TE).div_ceil(8);

    pub fn encode(&self, dest: &mut [u8]) -> Result<usize, Hcs300EncodeError> {
        let actual = dest.len();
        let out: &mut [u8; Self::CODEWORD_BYTES] = dest
            .first_chunk_mut::<{ Self::CODEWORD_BYTES }>()
            .ok_or(Hcs300EncodeError::BufferTooSmall {
                required: Self::CODEWORD_BYTES,
                actual,
            })?;
        out.fill(0);

        let mut cursor = BitCursor::new(out);

        // 1. Preamble: 23 alternating TE pulses (1, 0, 1, ..., 1)
        for i in 0..Self::PREAMBLE_TE {
            cursor.push_bit(i % 2 == 0);
        }

        // 2. Header GAP: 10 TE low pulses (0)
        cursor.skip(Self::HEADER_GAP_TE);

        // 3. Encrypted Portion: 32 bits, transmitted LSB first
        for i in 0..Self::ENCRYPTED_BITS {
            let bit = ((self.encrypted >> i) & 1) != 0;
            Self::encode_pwm(&mut cursor, bit);
        }

        // 4. Fixed Portion: 34 bits, transmitted LSB-first
        // Serial number: 28 bits
        for i in 0..Hcs300SerialNumber::BITS {
            let bit = ((self.serial_number.get() >> i) & 1) != 0;
            Self::encode_pwm(&mut cursor, bit);
        }

        // Button status: 4 bits (S3, S0, S1, S2)
        Self::encode_pwm(&mut cursor, self.button_status.s3());
        Self::encode_pwm(&mut cursor, self.button_status.s0());
        Self::encode_pwm(&mut cursor, self.button_status.s1());
        Self::encode_pwm(&mut cursor, self.button_status.s2());

        // VLOW bit
        Self::encode_pwm(&mut cursor, self.vlow);

        // RPT bit
        Self::encode_pwm(&mut cursor, self.repeat);

        Ok(0)
    }

    /// Encodes a single logic bit into 3 TE units:
    /// - 0 bit: 2 TE High, 1 TE Low (1, 1, 0)
    /// - 1 bit: 1 TE High, 2 TE Low (1, 0, 0)
    #[inline(always)]
    fn encode_pwm<const N: usize>(cursor: &mut BitCursor<'_, N>, bit: bool) {
        if bit {
            cursor.push_bit(true);
            cursor.push_bit(false);
            cursor.push_bit(false);
        } else {
            cursor.push_bit(true);
            cursor.push_bit(true);
            cursor.push_bit(false);
        }
    }
}

struct BitCursor<'a, const N: usize> {
    buf: &'a mut [u8; N],
    bit_pos: usize,
}

impl<'a, const N: usize> BitCursor<'a, N> {
    const MAX_BITS: usize = N * 8;

    #[inline(always)]
    fn new(buf: &'a mut [u8; N]) -> Self {
        Self { buf, bit_pos: 0 }
    }

    fn skip(&mut self, n: usize) {
        debug_assert!(self.bit_pos + n <= Self::MAX_BITS);
        self.bit_pos += n;
    }

    #[inline(always)]
    fn push_bit(&mut self, high: bool) {
        // Catches overflow bugs during tests or debug runs
        debug_assert!(
            self.bit_pos < Self::MAX_BITS,
            "BitCursor overflow: tried to write beyond {} bits",
            Self::MAX_BITS
        );

        if high {
            let byte_idx = self.bit_pos >> 3;
            let bit_idx = 7 - (self.bit_pos & 7);
            self.buf[byte_idx] |= 1 << bit_idx;
        }
        self.bit_pos += 1;
    }
}
