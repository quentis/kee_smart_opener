#ifndef HCS300_H
#define HCS300_H

#include <stdint.h>
#include <stdbool.h>

#include "sl_status.h"

// HCS300 protocol parameters
// All timings values are integer multiples of TE.
// TE is configurable between: 100us, 200us, 400us.
// Packet:
//   - Preamble: 23 TE (12 sync pulses) - 50% duty cycle
//   - Header: 10 TE gap
//   - Data: 66 bits -> 1 bit is 3 TE (PWM modulated)
//     - 0 bit: 2 TE high, 1 TE low
//     - 1 bit: 1 TE high, 2 TE low

// 50% duty cycle preamble
#define HCS300_PREAMBLE_TE            23

// Gap between preamble and data
#define HCS300_HEADER_GAP_TE          10

// Serial number, button code, VLOW and RPT bits
#define HCS300_FIXED_BITS             34
#define HCS300_ENCRYPTED_BITS         32
#define HCS300_BIT_TE                  3

// Data portion of code word (66 bits)
#define HCS300_DATA_BITS              (HCS300_ENCRYPTED_BITS + HCS300_FIXED_BITS)

// Total code word data length in TE units (each bit is encoded in 3 TE - PWM modulated)
#define HCS300_DATA_BITS_TE         (HCS300_DATA_BITS * HCS300_BIT_TE)

#define HCS300_CODEWORD_DATA_BYTES  ((HCS300_DATA_BITS_TE + 7) >> 3)
#define HCS300_CODEWORD_BYTES       ((HCS300_PREAMBLE_TE    \
                                    + HCS300_HEADER_GAP_TE  \
                                    + HCS300_DATA_BITS_TE + 7) >> 3)

// Button status getter macros
#define HCS300_BTN_STATUS_S0(btn_status)  ((btn_status) & HCS300_S0)
#define HCS300_BTN_STATUS_S1(btn_status)  ((btn_status) & HCS300_S1)
#define HCS300_BTN_STATUS_S2(btn_status)  ((btn_status) & HCS300_S2)
#define HCS300_BTN_STATUS_S3(btn_status)  ((btn_status) & HCS300_S3)

// The button inputs of HCS300 chip shall be activated to receive pwm signal.
typedef enum hcs300_sw_id {
  HCS300_S0 = 0x1,
  HCS300_S1 = 0x2,
  HCS300_S2 = 0x4,
  HCS300_S3 = 0x8,
} hcs300_sw_id_t;

sl_status_t hcs300_init(void);
sl_status_t hcs300_deinit(void);
sl_status_t hcs300_activate(hcs300_sw_id_t sw, bool repeat);
void hcs300_step(void);

void hcs300_proceed_cb(void);

sl_status_t hcs300_create_codeword(uint16_t hcs300_id,
                                   uint8_t *codeword,
                                   uint16_t *codeword_len,
                                   bool rpt,
                                   bool vlow,
                                   uint8_t btn_status,
                                   uint32_t serial,
                                   uint32_t encrypted);

sl_status_t hcs300_create_codeword_data(uint16_t hcs300_id,
                                        uint8_t *codeword,
                                        uint16_t *codeword_len,
                                        bool rpt,
                                        bool vlow,
                                        uint8_t btn_status,
                                        uint32_t serial,
                                        uint32_t encrypted);

void hcs300_on_rx_packet(uint16_t hcs300_id,
                         bool rpt,
                         bool vlow,
                         uint8_t btn_status,
                         uint32_t serial,
                         uint32_t encrypted);
#endif // HCS300_H

