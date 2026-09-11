/*
 * Copyright (c) 2012-2014 Wind River Systems, Inc.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>
#include <errno.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/input/input.h>
#include <zephyr/drivers/pwm.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/toolchain.h>

#include <app/drivers/cc1101.h>

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
#define HCS300_PREAMBLE_TE 23

// Gap between preamble and data
#define HCS300_HEADER_GAP_TE 10

// Serial number, button code, VLOW and RPT bits
#define HCS300_FIXED_BITS     34
#define HCS300_ENCRYPTED_BITS 32
#define HCS300_BIT_TE         3

// Data portion of code word (66 bits)
#define HCS300_DATA_BITS (HCS300_ENCRYPTED_BITS + HCS300_FIXED_BITS)

// Total code word data length in TE units (each bit is encoded in 3 TE - PWM modulated)
#define HCS300_DATA_BITS_TE (HCS300_DATA_BITS * HCS300_BIT_TE)

#define HCS300_CODEWORD_DATA_BYTES ((HCS300_DATA_BITS_TE + 7) >> 3)
#define HCS300_CODEWORD_BYTES                                                                      \
	((HCS300_PREAMBLE_TE + HCS300_HEADER_GAP_TE + HCS300_DATA_BITS_TE + 7) >> 3)

// Button status getter macros
#define HCS300_BTN_STATUS_S0(btn_status) ((btn_status) & HCS300_S0)
#define HCS300_BTN_STATUS_S1(btn_status) ((btn_status) & HCS300_S1)
#define HCS300_BTN_STATUS_S2(btn_status) ((btn_status) & HCS300_S2)
#define HCS300_BTN_STATUS_S3(btn_status) ((btn_status) & HCS300_S3)

#define HCS300_CODEWORD_TE (HCS300_PREAMBLE_TE + HCS300_HEADER_GAP_TE + HCS300_DATA_BITS_TE)

typedef enum hcs300_sw_id {
  HCS300_S0 = 0x1,
  HCS300_S1 = 0x2,
  HCS300_S2 = 0x4,
  HCS300_S3 = 0x8,
} hcs300_sw_id_t;

// Bit ordering within each byte of the codeword/data buffers (byte order of multi-byte
// words such as serial/encrypted is fixed by the protocol and unaffected by this setting)
typedef enum hcs300_bit_order {
	HCS300_BIT_ORDER_LSB_FIRST,
	HCS300_BIT_ORDER_MSB_FIRST,
} hcs300_bit_order_t;

static inline uint8_t hcs300_bit_offset(uint32_t bit_idx, hcs300_bit_order_t bit_order)
{
	uint8_t offset = bit_idx & 0x7;

	return (bit_order == HCS300_BIT_ORDER_MSB_FIRST) ? (7 - offset) : offset;
}

static const struct pwm_dt_spec pwm_led_red = PWM_DT_SPEC_GET(DT_NODELABEL(pwm_led_red));
static const struct pwm_dt_spec pwm_led_green = PWM_DT_SPEC_GET(DT_NODELABEL(pwm_led_green));
static const struct pwm_dt_spec pwm_led_blue = PWM_DT_SPEC_GET(DT_NODELABEL(pwm_led_blue));

static const struct gpio_dt_spec led_error = GPIO_DT_SPEC_GET(DT_NODELABEL(led_error), gpios);

static const struct gpio_dt_spec button_0 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_0), gpios);
static const struct gpio_dt_spec button_1 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_1), gpios);
static const struct gpio_dt_spec button_2 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_2), gpios);
static const struct gpio_dt_spec button_3 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_3), gpios);

static const struct gpio_dt_spec rf_tx_en = GPIO_DT_SPEC_GET(DT_NODELABEL(rf_tx_en), gpios);
static const struct gpio_dt_spec rf_rx_en = GPIO_DT_SPEC_GET(DT_NODELABEL(rf_rx_en), gpios);

static int rf_switch_init(void)
{
    if (!gpio_is_ready_dt(&rf_tx_en) || !gpio_is_ready_dt(&rf_rx_en)) {
        return -ENODEV;
    }

    gpio_pin_configure_dt(&rf_tx_en, GPIO_OUTPUT_ACTIVE);
    gpio_pin_configure_dt(&rf_rx_en, GPIO_OUTPUT_INACTIVE);
    return 0;
}

const struct device *cc1101 = DEVICE_DT_GET_ANY(ti_cc1101);

static void button_input_cb(struct input_event *evt, void *user_data)
{
	ARG_UNUSED(user_data);

	if (evt->sync == 0) {
		return;
	}

	printf("Button %d %s at %" PRIu32 "\n", evt->code, evt->value ? "pressed" : "released",
	       k_uptime_get_32());
}

INPUT_CALLBACK_DEFINE(NULL, button_input_cb, NULL);

static void led_test(void)
{
	pwm_set_pulse_dt(&pwm_led_red, 0);
	pwm_set_pulse_dt(&pwm_led_green, 0);
	pwm_set_pulse_dt(&pwm_led_blue, 0);
	gpio_pin_set_dt(&led_error, 1);
	k_msleep(1000);
	gpio_pin_set_dt(&led_error, 0);

	for (int i = 0; i <= 100; i++) {
		k_msleep(10);
		pwm_set_pulse_dt(&pwm_led_red, PWM_USEC(i * 10));
	}
	pwm_set_pulse_dt(&pwm_led_red, 0);
	k_msleep(1000);

	for (int i = 0; i <= 100; i++) {
		k_msleep(10);
		pwm_set_pulse_dt(&pwm_led_green, PWM_USEC(i * 10));
	}
	pwm_set_pulse_dt(&pwm_led_green, 0);
	k_msleep(1000);

	for (int i = 0; i <= 100; i++) {
		k_msleep(10);
		pwm_set_pulse_dt(&pwm_led_blue, PWM_USEC(i * 10));
	}
	pwm_set_pulse_dt(&pwm_led_blue, 0);
	k_msleep(1000);
}

static int create_codeword(uint8_t *codeword, uint16_t codeword_len, bool rpt, bool vlow,
			   uint8_t btn_status, uint32_t serial, uint32_t encrypted,
			   uint16_t guard_time_us, uint16_t te_us, bool preamble,
			   bool header, bool guard, hcs300_bit_order_t bit_order)
{
	uint16_t bit_len = HCS300_DATA_BITS_TE;
	uint8_t data[HCS300_CODEWORD_DATA_BYTES];

	memset(data, 0, sizeof(data));
	memset(codeword, 0, codeword_len);

	if (preamble) {
		bit_len += HCS300_PREAMBLE_TE;
	}
	if (header) {
		bit_len += HCS300_HEADER_GAP_TE;
	}
	if (guard) {
		bit_len += (guard_time_us + te_us - 1) / te_us;
	}
	uint16_t cw_len_min = (bit_len + 7) >> 3;

	if (codeword_len < cw_len_min) {
		return -ENOSPC;
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
	uint8_t btn_code = ((HCS300_BTN_STATUS_S3(btn_status) ? 1 : 0) << 0) |
			   ((HCS300_BTN_STATUS_S0(btn_status) ? 1 : 0) << 1) |
			   ((HCS300_BTN_STATUS_S1(btn_status) ? 1 : 0) << 2) |
			   ((HCS300_BTN_STATUS_S2(btn_status) ? 1 : 0) << 3);
	data[7] |= (btn_code << 4);
	data[8] = (vlow ? 1 : 0) << 0;
	data[8] |= (rpt ? 1 : 0) << 1;

	uint16_t cw_bit_idx = 0;
	if (preamble) {
		// Set preamble bits (50% duty cycle) into codeword array
		for (cw_bit_idx = 0; cw_bit_idx < HCS300_PREAMBLE_TE; cw_bit_idx += 2) {
			uint16_t byte_idx = cw_bit_idx >> 3;
			uint8_t bit_offset = hcs300_bit_offset(cw_bit_idx, bit_order);
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
			uint8_t bit_offset = hcs300_bit_offset(cw_bit_idx, bit_order);
			uint8_t pwm_bit = pwm_pattern[data_bit][pwm_idx];
			codeword[byte_idx] |= (pwm_bit << bit_offset);
		}
	}

	return cw_len_min;
}

int hcs300_create_codeword(uint8_t *codeword, uint16_t codeword_len, bool rpt,
			   bool vlow, uint8_t btn_status, uint32_t serial, uint32_t encrypted,
			   hcs300_bit_order_t bit_order)
{
	const uint16_t guard_time_us = 10000; 
	const uint16_t te_us = 400;
	return create_codeword(codeword, codeword_len, rpt, vlow, btn_status, serial,
			       encrypted, guard_time_us, te_us,
			       true,   // Preamble
			       true,   // Header
			       false,  // Guard time
			       bit_order);
}

int main(void)
{
	printf("Hello World! %s\n", CONFIG_BOARD_TARGET);

	rf_switch_init();

	if (!device_is_ready(led_error.port)) {
		printf("Error: LED device %s is not ready\n", led_error.port->name);
		return 0;
	}

	if (!pwm_is_ready_dt(&pwm_led_red)) {
		printf("Error: PWM device %s is not ready\n", pwm_led_red.dev->name);
		return 0;
	}
	if (!pwm_is_ready_dt(&pwm_led_green)) {
		printf("Error: PWM device %s is not ready\n", pwm_led_green.dev->name);
		return 0;
	}
	if (!pwm_is_ready_dt(&pwm_led_blue)) {
		printf("Error: PWM device %s is not ready\n", pwm_led_blue.dev->name);
		return 0;
	}
	int ret = gpio_pin_set_dt(&led_error, GPIO_OUTPUT_ACTIVE);
	if (ret < 0) {
		return 0;
	}

	if (!device_is_ready(button_0.port)) {
		printk("Error: button device %s is not ready\n", button_0.port->name);
		return -1;
	}

	if (!device_is_ready(button_1.port)) {
		printk("Error: button device %s is not ready\n", button_1.port->name);
		return -1;
	}

	if (!device_is_ready(button_2.port)) {
		printk("Error: button device %s is not ready\n", button_2.port->name);
		return -1;
	}

	if (!device_is_ready(button_3.port)) {
		printk("Error: button device %s is not ready\n", button_3.port->name);
		return -1;
	}

	// Turn off all LEDs
	pwm_set_pulse_dt(&pwm_led_red, 0);
	pwm_set_pulse_dt(&pwm_led_green, 0);
	pwm_set_pulse_dt(&pwm_led_blue, 0);
	gpio_pin_set_dt(&led_error, 0);

	uint8_t codeword[HCS300_CODEWORD_BYTES];
	ret = hcs300_create_codeword(codeword, sizeof(codeword), false, false, 0x01, 0x12345678,
				      0x9ABCDEF0, HCS300_BIT_ORDER_MSB_FIRST);
	if (ret < 0) {
		printf("Error creating codeword: %d\n", ret);
		return 0;
	}

	while (1) {
		cc1101_find_chip(cc1101);
		// gpio_pin_set_dt(&rf_rx_en, 0);
		// k_msleep(100);
		ret = cc1101_tx(cc1101, codeword, sizeof(codeword));
		// k_msleep(100);
		// gpio_pin_set_dt(&rf_rx_en, 1);
		if (ret < 0) {
			printf("Error transmitting codeword: %d\n", ret);
		}
		k_msleep(5000);
	}

	return 0;
}
