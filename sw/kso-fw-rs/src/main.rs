// This is a no_std application, so it does not link the Rust standard library.
// Note: #![no_std] is an inner attribute that applies to the entire crate.
#![no_std]
// The main is provided by the runtime, so we don't use the Rust main function entry point
#![no_main]

// Panic handler function is required for no_std applications to handle panic situations gracefully
use core::panic::PanicInfo;

// Alias our HAL
use rp235x_hal::{
    self as hal, Clock,
    gpio::{
        Function,
        PinState::{High, Low},
        PullDown, PullNone, PullUp,
    },
};

// Bring GPIO structs/functions into scope
use hal::gpio::{FunctionSpi, Pin};

// USB Device and Communication Class Device (CDC) support
use usb_device::{class_prelude::*, prelude::*};
use usbd_serial::SerialPort;

// SPI structs and functions
use embedded_hal::{digital::InputPin, spi::SpiBus, spi::SpiDevice};
use embedded_hal_bus::spi::ExclusiveDevice;

// Used for the rate/frequency type
use hal::fugit::RateExtU32;

// For working with non-heap strings
use core::fmt::Write;
use heapless::String;

// Custom panic handler: just loop forever
#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {}
}

// Copy boot metadata to .start_block so boot ROM knows how to boot our program
#[unsafe(link_section = ".start_block")]
#[used]
pub static IMAGE_DEF: hal::block::ImageDef = hal::block::ImageDef::secure_exe();

// Set external crystal frequency
const XOSC_CRYSTAL_FREQ: u32 = 12_000_000;

// Main entrypoint (custom defined for embedded targets)
#[hal::entry]
fn main() -> ! {
    // Get ownership of hardware peripherals
    let mut pac = hal::pac::Peripherals::take().unwrap();

    // Set up the watchdog and clocks
    let mut watchdog = hal::Watchdog::new(pac.WATCHDOG);
    let clocks = hal::clocks::init_clocks_and_plls(
        XOSC_CRYSTAL_FREQ,
        pac.XOSC,
        pac.CLOCKS,
        pac.PLL_SYS,
        pac.PLL_USB,
        &mut pac.RESETS,
        &mut watchdog,
    )
    .ok()
    .unwrap();

    // Single-cycle I/O block (fast GPIO)
    let sio = hal::Sio::new(pac.SIO);

    // Split off ownership of Peripherals struct, set pins to default state
    let pins = hal::gpio::Pins::new(
        pac.IO_BANK0,
        pac.PADS_BANK0,
        sio.gpio_bank0,
        &mut pac.RESETS,
    );

    // Configure button pins
    let mut btn0_pin = pins.gpio22.into_floating_input();
    let mut btn1_pin = pins.gpio26.into_floating_input();
    let mut btn2_pin = pins.gpio27.into_floating_input();
    let mut btn3_pin = pins.gpio28.into_floating_input();

    // Configure LEDs
    let mut led_err = pins.gpio12.into_push_pull_output_in_state(High);
    let mut rgb_led_red = pins.gpio11.into_push_pull_output_in_state(High);
    let mut rgb_led_green = pins.gpio10.into_push_pull_output_in_state(High);
    let mut rgb_led_blue = pins.gpio9.into_push_pull_output_in_state(High);

    // Configure CC1101 pins
    let mut c1101_en_pin = pins.gpio15.into_push_pull_output_in_state(High);
    let mut c1101_tx_en_pin = pins.gpio14.into_push_pull_output_in_state(Low);
    let mut c1101_rx_en_pin = pins.gpio13.into_push_pull_output_in_state(Low);

    // Configure SPI pins
    let spi0_tx = pins.gpio19.into_function::<hal::gpio::FunctionSpi>();
    let spi0_sck = pins.gpio18.into_function::<hal::gpio::FunctionSpi>();
    let spi0_rx = pins.gpio16.into_function::<hal::gpio::FunctionSpi>();
    let spi_cs = pins.gpio17.into_function::<hal::gpio::FunctionSioOutput>();

    // Configure SPI pins
    let spi_bus = hal::spi::Spi::<_, _, _, 8>::new(pac.SPI0, (spi0_tx, spi0_rx, spi0_sck));

    let spi_bus = spi_bus.init(
        &mut pac.RESETS,
        clocks.peripheral_clock.freq(),
        1.MHz(),
        embedded_hal::spi::MODE_0,
    );

    let mut spi = ExclusiveDevice::new_no_delay(spi_bus, spi_cs).unwrap();

    // Initialize and take ownership of the SPI peripheral

    // Move ownership of TIMER0 peripheral to create Timer struct
    let timer = hal::Timer::new_timer0(pac.TIMER0, &mut pac.RESETS, &clocks);

    let usb_bus = UsbBusAllocator::new(hal::usb::UsbBus::new(
        pac.USB,
        pac.USB_DPRAM,
        clocks.usb_clock,
        true,
        &mut pac.RESETS,
    ));

    // Configure USB as CDC
    let mut serial = SerialPort::new(&usb_bus);

    // Create a USB device with a fake VID/PID
    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x16c0, 0x27dd))
        .strings(&[StringDescriptors::default()
            .manufacturer("Fake company")
            .product("Serial port")
            .serial_number("Test")])
        .unwrap()
        .device_class(usbd_serial::USB_CLASS_CDC)
        .build();

    // Read buffer
    let mut rx_buf = [0u8; 64];
    let mut output = String::<64>::new();

    // Superloop
    let mut timestamp = timer.get_counter();

    loop {
        // Needs to be called at least every 10ms
        if usb_dev.poll(&mut [&mut serial]) {
            match serial.read(&mut rx_buf) {
                Ok(0) => {}
                Ok(_count) => {}
                Err(_e) => {}
            }
        }

        // Send message in every second (non-blocking)
        if (timer.get_counter() - timestamp).to_millis() >= 1_000 {
            timestamp = timer.get_counter();
            let _ = serial.write(b"hello!\r\n");

            let mut buffer: [u8; 2] = [0xF1, 0x00];
            if spi.transfer_in_place(&mut buffer).is_ok() {
                output.clear();
                write!(&mut output, "Version number: {:}\r\n", buffer[1]).unwrap();
                let _ = serial.write(output.as_bytes());
            } else {
                let _ = serial.write(b"spi transfer failed!\r\n");
            }
        }
    }
}
