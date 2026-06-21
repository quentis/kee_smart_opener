#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>

#include "hcs300.h"
#include "util.h"

#include "app_log.h"

#include "app_assert.h"

#include "sl_status.h"
#include "sl_common.h"

#include "sl_clock_manager.h"
#include "sl_hal_gpio.h"
#include "sl_hal_timer.h"
#include "sl_interrupt_manager.h"
#include "sl_sleeptimer.h"
#include "sl_component_catalog.h"

#ifdef SL_CATALOG_POWER_MANAGER_PRESENT
#include "sl_power_manager.h"
#endif

#include "dmadrv.h"

// TODO: Remove temporary workaround for missing comma in macro
#undef app_log_array_dump_level
#define app_log_array_dump_level(level, p_data, len, format) \
app_log_array_dump_level_s(level,                          \
  APP_LOG_ARRAY_DUMP_SEPARATOR,   \
  p_data,                         \
  len,                            \
  format)


// 50% duty cycle preamble means 12 pulses (half as many rounded down)
#define HCS300_PREAMBLE_PULSES        ((HCS300_PREAMBLE_TE + 1) / 2)

// HCS300 supports 4 buttons
#define HCS300_BUTTON_CODE_BITS        4

// Serial number stored in HCS300
#define HCS300_SERIAL_NUM_BITS        28

#define HCS300_SERIAL_NUM_OFFSET      HCS300_ENCRYPTED_BITS
#define HCS300_BUTTON_CODE_OFFSET     (HCS300_SERIAL_NUM_OFFSET + HCS300_SERIAL_NUM_BITS)
#define HCS300_VLOW_OFFSET            (HCS300_BUTTON_CODE_OFFSET + HCS300_BUTTON_CODE_BITS)
#define HCS300_RPT_OFFSET             (HCS300_VLOW_OFFSET + 1)

#define HCS300_MAX_PULSES             (HCS300_PREAMBLE_PULSES + HCS300_DATA_BITS)
#define HCS300_MAX_EDGES              (2 * HCS300_MAX_PULSES)

#define HCS300_MIN_CAPTURES(min_preamble_pulses) \
        (2 * ((min_preamble_pulses) + HCS300_DATA_BITS))

// There is an extra capture at the beginning when the first edge is detected.
// The first capture is always zero because the timer is stopped but in order
// to use DMA to transfer the capture values we need to reserve space for it.
// On the other hand, the last bit has 1 or 2 TE low at the end which is
// followed by TG guard time where no signal is sent which means low level is
// detected. There isn't any capture for the last low level, and consequently
// no space is needed to store it, however space is allocated for the last
// 1 or 2 TE low duration (stored manually) on PWM pin to ease the processing logic.
#define HCS300_MAX_CAPTURES         (HCS300_MAX_EDGES + 1)

#define HCS300_DATA_BITS_CAPTURES   (2 * HCS300_DATA_BITS)


#define HCS300_CODEWORD_TE          (HCS300_PREAMBLE_TE     \
                                     + HCS300_HEADER_GAP_TE \
                                     + HCS300_DATA_BITS_TE)



typedef struct hcs300_config {
  sl_gpio_t pwm_pin;
  sl_gpio_t s0_pin;
  uint16_t  activation_time_single_ms;
  uint16_t  activation_time_repeat_ms;
  uint16_t  guard_time_us;
  uint16_t  te_nominal_us;
  uint8_t   min_preamble_pulses;
  uint8_t   te_tolerance_init_pct;
  uint8_t   te_tolerance_prec_pct;
  TIMER_TypeDef *timer;
} hcs300_config_t;

typedef struct hcs300 {
  const hcs300_config_t *config;
  sl_sleeptimer_timer_handle_t activation_timer;
  volatile uint32_t captures[HCS300_MAX_CAPTURES];
  volatile uint16_t capture_idx;
  volatile uint16_t capture_len;
  uint16_t te_nominal_ticks;
} hcs300_t;

typedef enum hcs300_decode_result {
  HCS300_DECODE_OK,
  HCS300_DECODE_ERR_INVALID_TE
} hcs300_decode_result_t;

typedef struct hcs300_decoder {
  struct {
    uint32_t encrypted;
    uint32_t serial : 28;
    uint8_t s3 : 1;
    uint8_t s0 : 1;
    uint8_t s1 : 1;
    uint8_t s2 : 1;
    uint8_t vlow : 1;
    uint8_t rpt : 1;
  } data;
  uint32_t te_ticks;
  uint32_t te_ticks_sum;
  uint16_t capture_idx;
  uint16_t preamble_capture_cnt;
  uint8_t  data_bit_idx;
} hcs300_decoder_t;

// TODO: Hard code configuration for now
const hcs300_config_t hcs300_default_config = {
  .pwm_pin = {
    .port = SL_GPIO_PORT_D,
    .pin  = 2,
  }, // EXP_HEADER9
  .s0_pin = {
    .port = SL_GPIO_PORT_A,
    .pin  = 5,
  }, // EXP_HEADER7
  .activation_time_single_ms = 15,  // Debounce time on HCS300 is max 15ms
  .activation_time_repeat_ms = 500, // 500ms activation time sends 5 packets
  .guard_time_us = 10000,           // Guard time after packet is at least 10ms
  .te_nominal_us = 400,             // Nominal TE duration is 400us
  .min_preamble_pulses = 6,         // Minimum preamble pulses to accept packet
  .te_tolerance_init_pct = 20,      // 20% tolerance for 1 TE
  .te_tolerance_prec_pct =  2,      //  2% tolerance for 1 TE after calibration
  .timer = TIMER0,
};

static hcs300_t hcs300_instance = {
  .config = &hcs300_default_config,
  .captures = {0},
  .capture_idx = 0,
  .te_nominal_ticks = 0,
};

static hcs300_t *const hcs300 = &hcs300_instance;

static void init_gpio(void);
static void init_timer(void);

static void activation_timeout_cb(sl_sleeptimer_timer_handle_t *handle,
                                  void *data);
static bool is_within_tolerance(uint32_t value,
                                uint32_t target,
                                uint32_t tolerance);
static bool is_within_rel_tolerance(uint32_t value,
                                    uint32_t target,
                                    uint8_t rel_tolerance_pct);
static uint32_t ticks_to_us(uint32_t ticks);
static uint32_t us_to_ticks(uint32_t us);

static bool is_te_valid(uint32_t te_measured_ticks, uint8_t rel_tolerance);

static sl_status_t process_preamble_header(hcs300_t *hcs300,
                                           hcs300_decoder_t *decoder);
static sl_status_t process_data(hcs300_t *hcs300,
                                hcs300_decoder_t *decoder);

static sl_status_t create_codeword(hcs300_t *hcs300,
                                   uint8_t *codeword,
                                   uint16_t *codeword_len,
                                   bool rpt,
                                   bool vlow,
                                   uint8_t btn_status,
                                   uint32_t serial,
                                   uint32_t encrypted,
                                   uint16_t te_us,
                                   bool preamble,
                                   bool header,
                                   bool guard);

sl_status_t hcs300_init(void)
{
  sl_status_t sc;

  sc = sl_clock_manager_enable_bus_clock(SL_BUS_CLOCK_GPIO);
  sc = sl_clock_manager_enable_bus_clock(SL_BUS_CLOCK_TIMER0);

  if (sc != SL_STATUS_OK) {
    return sc;
  }

  hcs300->te_nominal_ticks = us_to_ticks(hcs300->config->te_nominal_us);

  init_gpio();
  init_timer();

  #ifdef SL_CATALOG_POWER_MANAGER_PRESENT
  sl_power_manager_add_em_requirement(SL_POWER_MANAGER_EM1);
  #endif

  return SL_STATUS_OK;
}

sl_status_t hcs300_deinit(void)
{
  // TODO
  return SL_STATUS_NOT_SUPPORTED;
}

void hcs300_step(void)
{
  sl_status_t sc;

  if (hcs300->capture_len != 0) {
    hcs300_decoder_t decoder;
    memset(&decoder, 0, sizeof(decoder));

    // TODO: Add function
    if (hcs300->capture_len > ARRAY_SIZE(hcs300->captures)) {
      app_log_error("HCS300 capture buffer overflow (%u/%u)" APP_LOG_NL,
                    hcs300->capture_len,
                    (unsigned)ARRAY_SIZE(hcs300->captures));
      hcs300->capture_len = 0;
      return;
    }

    // Skip the first capture which is always zero
    decoder.capture_idx = 1;

    app_log_debug("HCS300 captures: ");
    app_log_array_dump_debug(hcs300->captures, hcs300->capture_len, "%lu");
    app_log_nl();

    sc = process_preamble_header(hcs300, &decoder);

    if (sc != SL_STATUS_OK) {
      hcs300->capture_len = 0;
      return;
    }

    sc = process_data(hcs300, &decoder);
    hcs300->capture_len = 0;

    if (sc == SL_STATUS_OK) {
        app_log_info("HCS300 packet received: "
                    "RPT=%u VLOW=%u S0=%u S1=%u S2=%u S3=%u "
                    "SERIAL=0x%08lX ENC=0x%08lX" APP_LOG_NL,
                    decoder.data.rpt,
                    decoder.data.vlow,
                    decoder.data.s0,
                    decoder.data.s1,
                    decoder.data.s2,
                    decoder.data.s3,
                    (uint32_t) decoder.data.serial,
                    decoder.data.encrypted);

        uint8_t btn_status = decoder.data.s0
                          | (decoder.data.s1 << 1)
                          | (decoder.data.s2 << 2)
                          | (decoder.data.s3 << 3);
        hcs300_on_rx_packet(0, // TODO: HCS300 ID
                            decoder.data.rpt,
                            decoder.data.vlow,
                            btn_status,
                            decoder.data.serial,
                            decoder.data.encrypted);
    }
  }
}

sl_status_t hcs300_create_codeword(uint16_t hcs300_id,
                                   uint8_t *codeword,
                                   uint16_t *codeword_len,
                                   bool rpt,
                                   bool vlow,
                                   uint8_t btn_status,
                                   uint32_t serial,
                                   uint32_t encrypted)
{
  (void) hcs300_id;
  return create_codeword(hcs300,
                         codeword,
                         codeword_len,
                         rpt,
                         vlow,
                         btn_status,
                         serial,
                         encrypted,
                         hcs300->te_nominal_ticks,
                         true,  // Preamble
                         true,  // Header
                         false); // Guard time
}

sl_status_t hcs300_create_codeword_data(uint16_t hcs300_id,
                                        uint8_t *codeword,
                                        uint16_t *codeword_len,
                                        bool rpt,
                                        bool vlow,
                                        uint8_t btn_status,
                                        uint32_t serial,
                                        uint32_t encrypted)
{
  (void) hcs300_id;
  return create_codeword(hcs300,
                         codeword,
                         codeword_len,
                         rpt,
                         vlow,
                         btn_status,
                         serial,
                         encrypted,
                         hcs300->te_nominal_ticks,
                         false,  // Preamble
                         false,  // Header
                         false); // Guard time
}

static sl_status_t process_preamble_header(hcs300_t *hcs300,
                                           hcs300_decoder_t *decoder)
{
  uint32_t pulse_width = 0;

  while (decoder->capture_idx < hcs300->capture_len) {
    // Each pulse in preamble should be about 23 TE (50% duty cycle)
    pulse_width = hcs300->captures[decoder->capture_idx];

    if (decoder->capture_idx >= 2 *hcs300->config->min_preamble_pulses) {
      if (is_within_rel_tolerance(pulse_width,
                                  HCS300_HEADER_GAP_TE * decoder->te_ticks,
                                  hcs300->config->te_tolerance_prec_pct)) {
        decoder->capture_idx++;
        // The header is zero and the codeword array is already cleared so
        // continue with data decoding
        break;
      }
    }

    decoder->te_ticks_sum += pulse_width;
    decoder->preamble_capture_cnt++;
    decoder->te_ticks = decoder->te_ticks_sum / decoder->preamble_capture_cnt;
    decoder->capture_idx++;
  }

  app_log_debug("HCS300 preamble detected (%u pulses)" APP_LOG_NL,
                (decoder->preamble_capture_cnt + 1) / 2);
  app_log_debug("HCS300 measured TE average: %lu us" APP_LOG_NL,
                ticks_to_us(decoder->te_ticks));
  app_log_debug("HCS300 header detected (%lu us)" APP_LOG_NL,
                ticks_to_us(pulse_width));

  return SL_STATUS_OK;
}

static sl_status_t decode_next_pwm(hcs300_t *hcs300, hcs300_decoder_t *decoder, uint8_t *bit)
{
  if (decoder->capture_idx + 1 >= hcs300->capture_len) {
    return SL_STATUS_INVALID_COUNT;
  }

  uint32_t high_duration = hcs300->captures[decoder->capture_idx];
  uint32_t low_duration  = hcs300->captures[decoder->capture_idx + 1];

  if (is_within_rel_tolerance(high_duration,
                              2 * decoder->te_ticks,
                              hcs300->config->te_tolerance_prec_pct)
      && is_within_rel_tolerance(low_duration,
                                 1 * decoder->te_ticks,
                                 hcs300->config->te_tolerance_prec_pct)) {
    // Detected a '0' bit
    *bit = 0;
  } else if (is_within_rel_tolerance(high_duration,
                                     1 * decoder->te_ticks,
                                     hcs300->config->te_tolerance_prec_pct)
             && is_within_rel_tolerance(low_duration,
                                        2 * decoder->te_ticks,
                                        hcs300->config->te_tolerance_prec_pct)) {
    // Detected a '1' bit
    *bit = 1;
  } else {
    return SL_STATUS_INVALID_RANGE;
  }

  decoder->capture_idx += 2;

  return SL_STATUS_OK;
}

static sl_status_t store_data_bit(hcs300_decoder_t *decoder, uint8_t bit)
{
  // Data portion of code word - which starts after header - has the following structure: (66 bits)
  // Note: multiple bits are sent in LSB first order
  //   - Encrypted data: 32 bits
  //   - Serial number: 28 bits
  //   - Button code: 4 bits (s3,s0,s1,s2)
  //   - VLOW: 1 bit
  //   - RPT: 1 bit

  if (decoder->data_bit_idx < HCS300_SERIAL_NUM_OFFSET) {
    decoder->data.encrypted >>= 1;
    if (bit) {
      decoder->data.encrypted |= 0x80000000;
    }
  } else if (decoder->data_bit_idx < HCS300_BUTTON_CODE_OFFSET) {
    decoder->data.serial >>= 1;
    if (bit) {
      decoder->data.serial |= 0x08000000;
    }
  } else if (decoder->data_bit_idx < HCS300_VLOW_OFFSET) {
    // Button code bits
    if (decoder->data_bit_idx == HCS300_BUTTON_CODE_OFFSET) {
      decoder->data.s3 = bit;
    } else if (decoder->data_bit_idx == HCS300_BUTTON_CODE_OFFSET + 1) {
      decoder->data.s0 = bit;
    } else if (decoder->data_bit_idx == HCS300_BUTTON_CODE_OFFSET + 2) {
      decoder->data.s1 = bit;
    } else if (decoder->data_bit_idx == HCS300_BUTTON_CODE_OFFSET + 3) {
      decoder->data.s2 = bit;
    }
  } else if (decoder->data_bit_idx == HCS300_VLOW_OFFSET) {
    decoder->data.vlow = bit;
  } else if (decoder->data_bit_idx == HCS300_RPT_OFFSET) {
    decoder->data.rpt = bit;
  } else {
    // Should not happen
    return SL_STATUS_INVALID_RANGE;
  }
  decoder->data_bit_idx++;

  return SL_STATUS_OK;
}

static sl_status_t process_data(hcs300_t *hcs300,
                                hcs300_decoder_t *decoder)
{
  if (hcs300->capture_len >= ARRAY_SIZE(hcs300->captures)) {
    // Each bit is 3 TE, 1 or 2 TE low at the end is missing because the guard
    // time follows with low level so there isn't any edge to capture it.
    // Space is reserved for this last 1 or 2 TE low duration to ease processing.
    // This means the captures array can't be completely full.
    return SL_STATUS_INVALID_COUNT;
  }

  // Add last fake capture value for easier processing.
  uint32_t last_capture = hcs300->captures[hcs300->capture_len - 1];
  if (is_within_rel_tolerance(last_capture,
                              decoder->te_ticks,
                              hcs300->config->te_tolerance_prec_pct)) {
    hcs300->captures[hcs300->capture_len] = 2 * decoder->te_ticks;
  } else {
    hcs300->captures[hcs300->capture_len] = decoder->te_ticks;
  }
  hcs300->capture_len++;

  if (hcs300->capture_len - decoder->capture_idx != HCS300_DATA_BITS_CAPTURES) {
    return SL_STATUS_INVALID_COUNT;
  }

  // Each bit is represented by 2 captures (high and low)
  while (decoder->capture_idx + 1 < hcs300->capture_len) {
    uint8_t bit;
    sl_status_t sc = decode_next_pwm(hcs300, decoder, &bit);
    if (sc != SL_STATUS_OK) {
      return sc;
    }

    sc = store_data_bit(decoder, bit);
    if (sc != SL_STATUS_OK) {
      return sc;
    }
  }

  return SL_STATUS_OK;
}

static void init_gpio(void)
{
  // Configure PD2 pin as input with the pull-up and filter enabled
  sl_hal_gpio_set_pin_mode(&hcs300->config->pwm_pin,
                           SL_GPIO_MODE_INPUT_PULL_FILTER,
                           0);

  // Configure S0 pin as output and set it to low (no operation)
  sl_hal_gpio_set_pin_mode(&hcs300->config->s0_pin,
                           SL_GPIO_MODE_PUSH_PULL,
                           0);
}

static void init_timer(void)
{
  TIMER_TypeDef *timer = hcs300->config->timer;

  // Configure TIMER0 in input capture mode
  sl_hal_timer_config_t timer_config = SL_HAL_TIMER_INIT_DEFAULT;
  timer_config.input_rise_action = SL_HAL_TIMER_INPUT_ACTION_RELOAD_START;
  timer_config.input_fall_action = SL_HAL_TIMER_INPUT_ACTION_RELOAD_START;

  // Configure channel for input capture
  sl_hal_timer_channel_config_t chn_config_0 = SL_HAL_TIMER_CHANNEL_INIT_DEFAULT;

  // Select capture mode for channel 0
  chn_config_0.channel_mode = SL_HAL_TIMER_CHANNEL_MODE_CAPTURE;
  chn_config_0.input_type = SL_HAL_TIMER_CHANNEL_INPUT_PIN;
  chn_config_0.input_capture_edge = SL_HAL_TIMER_CHANNEL_EDGE_BOTH;
  chn_config_0.input_capture_event = SL_HAL_TIMER_CHANNEL_EVENT_EVERY_EDGE;
  chn_config_0.filter = true;

  // Route the PD2 pin to TIMER0 capture/compare channel 0 and enable
  // On Series 2, routing must be done after channel initialization
  GPIO->TIMERROUTE[0].CC0ROUTE = (hcs300->config->pwm_pin.port << _GPIO_TIMER_CC0ROUTE_PORT_SHIFT)
                                 | (hcs300->config->pwm_pin.pin << _GPIO_TIMER_CC0ROUTE_PIN_SHIFT);
  GPIO->TIMERROUTE[0].ROUTEEN  = GPIO_TIMER_ROUTEEN_CC0PEN;

  // Initialize channel configuration (this also disables the timer temporarily)
  sl_hal_timer_channel_init(timer, 0, &chn_config_0);

  // Initialize timer (this disables the timer temporarily)
  sl_hal_timer_init(timer, &timer_config);

  // Enable interrupts
  sl_hal_timer_enable_interrupts(timer, TIMER_IEN_OF);
  sl_hal_timer_enable_interrupts(timer, TIMER_IEN_CC0);
  sl_interrupt_manager_enable_irq(TIMER0_IRQn);

  // Finally enable the timer
  sl_hal_timer_enable(timer);

  // Set guard time as top value
  uint32_t guard_time_ticks = us_to_ticks(hcs300->config->guard_time_us);
  sl_hal_timer_set_top(timer, guard_time_ticks);
}

void TIMER0_IRQHandler(void)
{
  TIMER_TypeDef *timer = hcs300->config->timer;
  uint32_t pending = sl_hal_timer_get_pending_interrupts(timer);

  if (pending & TIMER_IF_CC0) {
    // Clear interrupt flag
    sl_hal_timer_clear_interrupts(timer, TIMER_IF_CC0);

    do {
      uint32_t capture = sl_hal_timer_channel_get_capture(timer, 0);

      // The capture_idx is non-negative here
      if (hcs300->capture_idx < ARRAY_SIZE(hcs300->captures)) {
        hcs300->captures[hcs300->capture_idx++] = capture;
      } else {
        hcs300->capture_idx++;
      }
    } while ((sl_hal_timer_get_status(timer) & TIMER_STATUS_ICFEMPTY0) == 0);
  }

  if (pending & TIMER_IF_OF) {
    hcs300->capture_len = hcs300->capture_idx;
    hcs300->capture_idx = 0;
    while ((sl_hal_timer_get_status(timer) & TIMER_STATUS_ICFEMPTY0) == 0) {
      // Make sure no captures are left in the fifo at the end of codeword because that could
      // compromise the next reception.
      (void) sl_hal_timer_channel_get_capture(timer, 0);
    }
    sl_hal_timer_stop(timer);
    sl_hal_timer_set_counter(timer, 0);
    // Clear interrupt flag
    sl_hal_timer_clear_interrupts(timer, TIMER_IF_OF);
    hcs300_proceed_cb();
  }
}

sl_status_t hcs300_activate(hcs300_sw_id_t sw, bool repeat)
{
  if (sw == 0 || sw > 0xF) {
    return SL_STATUS_INVALID_PARAMETER;
  }

  if (sw & HCS300_S0) {
    sl_status_t sc;
    uint16_t activation_time_ms;

    sl_hal_gpio_set_pin(&hcs300->config->s0_pin);

    if (repeat) {
      activation_time_ms = hcs300->config->activation_time_repeat_ms;
    } else {
      activation_time_ms = hcs300->config->activation_time_single_ms;
    }
    activation_time_ms = sl_sleeptimer_ms_to_tick(activation_time_ms);

    // Start timer to deactivate the button later
    sc = sl_sleeptimer_restart_timer(&hcs300->activation_timer,
                                     activation_time_ms,
                                     activation_timeout_cb,
                                     NULL,
                                     0,
                                     0);
    app_assert_status(sc);
  }

  return SL_STATUS_OK;
}

static void activation_timeout_cb(sl_sleeptimer_timer_handle_t *handle, void *data)
{
  (void)handle;
  (void)data;

  // Deactivate all buttons
  sl_hal_gpio_clear_pin(&hcs300->config->s0_pin);
}

SL_WEAK void hcs300_proceed_cb(void)
{
  // TODO
}

static bool is_within_tolerance(uint32_t value,
                                uint32_t target,
                                uint32_t tolerance)
{
  return (value >= (target - tolerance)) && (value <= (target + tolerance));
}

static bool is_within_rel_tolerance(uint32_t value,
                                    uint32_t target,
                                    uint8_t rel_tolerance_pct)
{
  uint32_t tolerance = (target * rel_tolerance_pct) / 100;
  return is_within_tolerance(value, target, tolerance);
}

static uint32_t ticks_to_us(uint32_t ticks)
{
  sl_status_t sc;
  uint32_t freq_hz = 0;
  sc = sl_clock_manager_get_clock_branch_frequency(SL_CLOCK_BRANCH_EM01GRPCCLK,
                                                   &freq_hz);
  app_assert_status(sc);

  return (uint32_t)(((uint64_t) ticks * 1000000U + freq_hz / 2) / freq_hz);
}

static uint32_t us_to_ticks(uint32_t us)
{
  sl_status_t sc;
  uint32_t freq_hz = 0;
  sc = sl_clock_manager_get_clock_branch_frequency(SL_CLOCK_BRANCH_EM01GRPCCLK,
                                                   &freq_hz);
  app_assert_status(sc);
  return (uint32_t)(((uint64_t) us * freq_hz + 500000U) / 1000000U);
}

static sl_status_t create_codeword(hcs300_t *hcs300,
                                   uint8_t *codeword,
                                   uint16_t *codeword_len,
                                   bool rpt,
                                   bool vlow,
                                   uint8_t btn_status,
                                   uint32_t serial,
                                   uint32_t encrypted,
                                   uint16_t te_us,
                                   bool preamble,
                                   bool header,
                                   bool guard)
{
  uint16_t bit_len = HCS300_DATA_BITS_TE;
  uint8_t data[HCS300_CODEWORD_DATA_BYTES];

  memset(data, 0, sizeof(data));
  memset(codeword, 0, *codeword_len);

  if (preamble) {
    bit_len += HCS300_PREAMBLE_TE;
  }
  if (header) {
    bit_len += HCS300_HEADER_GAP_TE;
  }
  if (guard) {
    bit_len += (hcs300->config->guard_time_us + te_us - 1) / te_us;
  }
  uint16_t cw_len_min = (bit_len + 7) >> 3;

  if (*codeword_len < cw_len_min) {
    return SL_STATUS_WOULD_OVERFLOW;
  }

  data[0] = encrypted & 0xFF;
  data[1] = (encrypted >> 8) & 0xFF;
  data[2] = (encrypted >> 16) & 0xFF;
  data[3] = (encrypted >> 24) & 0xFF;
  data[4] = serial & 0xFF;
  data[5] = (serial >> 8) & 0xFF;
  data[6] = (serial >> 16) & 0xFF;
  data[7] = (serial >> 24) & 0x0F;
  // Button code bits: S3, S0, S1, S2 (LSB first)
  uint8_t btn_code = ((HCS300_BTN_STATUS_S3(btn_status) ? 1 : 0) << 0)
                   | ((HCS300_BTN_STATUS_S0(btn_status) ? 1 : 0) << 1)
                   | ((HCS300_BTN_STATUS_S1(btn_status) ? 1 : 0) << 2)
                   | ((HCS300_BTN_STATUS_S2(btn_status) ? 1 : 0) << 3);
  data[7] |= (btn_code << 4);
  data[8] = (vlow ? 1 : 0) << 0;
  data[8] |= (rpt  ? 1 : 0) << 1;

  uint16_t cw_bit_idx = 0;
  if (preamble) {
    // Set preamble bits (50% duty cycle) into codeword array
    for (cw_bit_idx = 0; cw_bit_idx < HCS300_PREAMBLE_TE; cw_bit_idx +=2) {
      uint16_t byte_idx = cw_bit_idx >> 3;
      uint8_t bit_offset = cw_bit_idx & 0x7;
      codeword[byte_idx] |= (1 << bit_offset);
    }
  }

  if (header) {
    // The codeword array is already cleared so just advance the index
    cw_bit_idx += HCS300_HEADER_GAP_TE;
  }

  for (uint32_t data_bit_idx = 0; data_bit_idx < HCS300_DATA_BITS; data_bit_idx++) {
    uint8_t data_byte = data[data_bit_idx >> 3];
    uint8_t data_bit = (data_byte >> (data_bit_idx & 0x7)) & 0x1;

    uint8_t pwm_pattern[2][3] = {
      {1, 1, 0}, // logical 0
      {1, 0, 0}  // logical 1
    };

    for (uint8_t pwm_idx = 0; pwm_idx < HCS300_BIT_TE; pwm_idx++, cw_bit_idx++) {
        uint32_t byte_idx = cw_bit_idx >> 3;
        uint8_t bit_offset = cw_bit_idx & 0x7;
        uint8_t pwm_bit = pwm_pattern[data_bit][pwm_idx];
        codeword[byte_idx] |= (pwm_bit << bit_offset);
    }
  }
  *codeword_len = cw_len_min;
  return SL_STATUS_OK;
}

SL_WEAK void hcs300_on_rx_packet(uint16_t hcs300_id,
                                 bool rpt,
                                 bool vlow,
                                 uint8_t btn_status,
                                 uint32_t serial,
                                 uint32_t encrypted)
{
  (void)hcs300_id;
  (void)rpt;
  (void)vlow;
  (void)btn_status;
  (void)serial;
  (void)encrypted;
}