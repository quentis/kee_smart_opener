/*
 * Copyright (c) 2012-2014 Wind River Systems, Inc.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/input/input.h>
#include <zephyr/drivers/pwm.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/toolchain.h>

static const struct pwm_dt_spec pwm_led_red = PWM_DT_SPEC_GET(DT_NODELABEL(pwm_led_red));
static const struct pwm_dt_spec pwm_led_green = PWM_DT_SPEC_GET(DT_NODELABEL(pwm_led_green));
static const struct pwm_dt_spec pwm_led_blue = PWM_DT_SPEC_GET(DT_NODELABEL(pwm_led_blue));

static const struct gpio_dt_spec led_error = GPIO_DT_SPEC_GET(DT_NODELABEL(led_error), gpios);

static const struct gpio_dt_spec button_0 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_0), gpios);
static const struct gpio_dt_spec button_1 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_1), gpios);
static const struct gpio_dt_spec button_2 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_2), gpios);
static const struct gpio_dt_spec button_3 = GPIO_DT_SPEC_GET(DT_NODELABEL(button_3), gpios);

static void button_input_cb(struct input_event *evt, void *user_data) {
	ARG_UNUSED(user_data);

	if (evt->sync == 0) {
		return;
	}

	printf("Button %d %s at %" PRIu32 "\n",
	       evt->code,
	       evt->value ? "pressed" : "released",
	       k_uptime_get_32());
}

INPUT_CALLBACK_DEFINE(NULL, button_input_cb, NULL);

static void led_test(void) {
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

int main(void)
{
	printf("Hello World! %s\n", CONFIG_BOARD_TARGET);

	if (!device_is_ready(led_error.port)) {
		printf("Error: LED device %s is not ready\n", led_error.port->name);
		return 0;
	}

	if (!pwm_is_ready_dt(&pwm_led_red)) {
		printf("Error: PWM device %s is not ready\n",
		       pwm_led_red.dev->name);
		return 0;
	}
	if (!pwm_is_ready_dt(&pwm_led_green)) {
		printf("Error: PWM device %s is not ready\n",
		       pwm_led_green.dev->name);
		return 0;
	}
	if (!pwm_is_ready_dt(&pwm_led_blue)) {
		printf("Error: PWM device %s is not ready\n",
		       pwm_led_blue.dev->name);
		return 0;
	}
	int ret = gpio_pin_configure_dt(&led_error, GPIO_OUTPUT_ACTIVE);
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

	while(1) {
		k_msleep(1000);
	}

	return 0;
}
