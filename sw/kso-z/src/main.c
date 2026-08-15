#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/gpio.h>

LOG_MODULE_REGISTER(main, CONFIG_LOG_DEFAULT_LEVEL);

static const struct gpio_dt_spec rgb_led_red = GPIO_DT_SPEC_GET(DT_NODELABEL(rgb_led_red), gpios);
static const struct gpio_dt_spec rgb_led_green = GPIO_DT_SPEC_GET(DT_NODELABEL(rgb_led_green), gpios);
static const struct gpio_dt_spec rgb_led_blue = GPIO_DT_SPEC_GET(DT_NODELABEL(rgb_led_blue), gpios);

int main(void)
{
    printk("Hello World from Pico!\n");

    if (!gpio_is_ready_dt(&rgb_led_red))
    {
        return 0;
    }

    if (!gpio_is_ready_dt(&rgb_led_green))
    {
        return 0;
    }

    if (!gpio_is_ready_dt(&rgb_led_blue))
    {
        return 0;
    }

    int ret;

    ret = gpio_pin_configure_dt(&rgb_led_red, GPIO_OUTPUT_INACTIVE);
    if (ret < 0)
    {
        return 0;
    }

    ret = gpio_pin_configure_dt(&rgb_led_green, GPIO_OUTPUT_INACTIVE);
    if (ret < 0)
    {
        return 0;
    }

    ret = gpio_pin_configure_dt(&rgb_led_blue, GPIO_OUTPUT_INACTIVE);
    if (ret < 0)
    {
        return 0;
    }

    while (1)
    {
        printk("Running on %s...\n", CONFIG_BOARD);
        ret = gpio_pin_toggle_dt(&rgb_led_red);
        if (ret < 0)
        {
            return 0;
        }
        ret = gpio_pin_toggle_dt(&rgb_led_green);
        if (ret < 0)
        {
            return 0;
        }
        ret = gpio_pin_toggle_dt(&rgb_led_blue);
        if (ret < 0)
        {
            return 0;
        }
        k_sleep(K_MSEC(1000));
    }

    return 0;
}
