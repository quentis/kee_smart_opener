#![no_std]
#![no_main]
#![allow(unused)]

use cc1101_embassy::{Cc1101, Modulation, PacketLength, RadioConfig, SyncMode, TxPower};
use defmt as _;
use defmt::{debug, error, info, warn};
use defmt_rtt as _;
use embassy_embedded_hal::shared_bus::asynch::spi::SpiDevice;
use embassy_executor::Spawner;
use embassy_rp::gpio::{Input, Level, Output, Pull};
use embassy_rp::peripherals::{DMA_CH0, DMA_CH1, PIO0};
use embassy_rp::pio::program::pio_asm;
use embassy_rp::pio::{Common, FifoJoin, Pio, PioPin, StateMachine};
use embassy_rp::pio_programs::clock_divider::calculate_pio_clock_divider;
use embassy_rp::spi::{self, Phase, Polarity, Spi};
use embassy_rp::{Peri, binary_info, pio};
use embassy_rp::{bind_interrupts, dma};
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embassy_sync::mutex::Mutex;
use embassy_time::{Instant, Timer};
use embedded_hal_async::spi::{Operation, SpiDevice as _};
use fugit::{ExtU32, Hertz, HertzU32, RateExtU32};
use panic_probe as _;
use static_cell::StaticCell;

mod hcs300;
use hcs300::Hcs300Packet;

use crate::hcs300::{Hcs300ButtonStatus, Hcs300SerialNumber};

type AsyncSpi0 = Spi<'static, embassy_rp::peripherals::SPI0, spi::Async>;

static SPI_BUS: StaticCell<Mutex<NoopRawMutex, AsyncSpi0>> = StaticCell::new();

bind_interrupts!(struct Irqs {
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>, dma::InterruptHandler<DMA_CH1>;
    PIO0_IRQ_0 => pio::InterruptHandler<PIO0>;
});

fn setup_pio_task_sm0<'d>(
    pio: &mut Common<'d, PIO0>,
    sm: &mut StateMachine<'d, PIO0, 0>,
    hcs300_pwm_pin: Peri<'d, impl PioPin>,
) {
    #[rustfmt::skip]
    let prog = pio_asm!(
        ".wrap_target",
        "init:",
            "pull",
        "load_idle_timeout:",
            "mov y, osr",
            "wait 0 pin 0",
        "wait_idle:",
            "jmp pin load_idle_timeout",
            "jmp y-- wait_idle [3]",
        "wait_codeword_start:",
            "set x, 0",
            "mov x, ~x",
            "mov y, osr",
            "wait 1 pin 0",
        "wait_low_1:",
            "jmp pin wait_low_2",
            "jmp falling_edge",
        "wait_low_2:",
            "jmp y-- wait_low_3",
            "jmp stuck_high",
        "wait_low_3:",
            "jmp x-- wait_low_1 [2]",
        "falling_edge:",
            "in x 32",
            "push noblock",
            "mov y, osr",
            "jmp x-- wait_high_1",
        "wait_high_1:",
            "jmp pin rising_edge",
        "wait_high_2:",
            "jmp y-- wait_high_3",
            "irq wait 0 ",
            "jmp wait_codeword_start",
        "wait_high_3:",
            "jmp x-- wait_high_1 [2]",
        "rising_edge:",
            "in x 32",
            "push noblock",
            "mov y, osr [1]",
            "jmp x-- wait_low_1",
        "stuck_high:",
            "wait 0 pin 0",
            "irq set 1",
            "jmp wait_codeword_start",
        ".wrap",
    );
    const PROG_START_OFFSET: u8 = 4;
    let mut cfg = pio::Config::default();
    let loaded_prog = &pio.load_program(&prog.program);
    debug!("HCS300 PIO0 origin: {}", loaded_prog.origin);
    cfg.use_program(loaded_prog, &[]);
    let in_pin = pio.make_pio_pin(hcs300_pwm_pin);
    cfg.set_in_pins(&[&in_pin]);
    cfg.set_jmp_pin(&in_pin);
    cfg.clock_divider = calculate_pio_clock_divider(5_000_000);
    sm.set_config(&cfg);
}

#[embassy_executor::task]
async fn pio_task_sm0(mut sm: StateMachine<'static, PIO0, 0>) {
    sm.set_enable(true);

    sm.tx().push(10_000);
    let addr = sm.get_addr();
    debug!("Address: {}", addr);
    let mut count = 0;
    let mut last_record: u32 = 0xFFFF_FFFF;
    loop {
        let v = sm.rx().wait_pull().await;
        let addr = sm.get_addr();
        debug!("Address: {}", addr);
        info!(
            "Pulled {} from FIFO -> {} (count: {})",
            !v,
            last_record - v,
            count
        );
        count += 1;
        last_record = v;
    }
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    info!("Starting...");
    let p = embassy_rp::init(Default::default());

    // let mut led_rgb_blue = Output::new(p.PIN_9, Level::Low);
    // let mut led_rgb_green = Output::new(p.PIN_10, Level::Low);
    // let mut led_rgb_red = Output::new(p.PIN_11, Level::Low);

    // let mut led_err_red = Output::new(p.PIN_12, Level::Low);

    let mut led_run_green = Output::new(p.PIN_25, Level::High);

    // Configure HCS300 pins
    let mut hcs300_pwm_pin = p.PIN_8;
    let mut pio = Pio::new(p.PIO0, Irqs);

    // // Configure CC1101 pins
    // let mut cc1101_en = Output::new(p.PIN_15, Level::Low);
    // let mut cc1101_tx_en = Output::new(p.PIN_14, Level::Low);
    // let mut cc1101_rx_en = Output::new(p.PIN_13, Level::Low);

    // let mut spi_config = spi::Config::default();
    // spi_config.frequency = 1_000_000;
    // spi_config.phase = Phase::CaptureOnFirstTransition;
    // spi_config.polarity = Polarity::IdleLow;

    // let cs = Output::new(p.PIN_17, Level::High);

    // // Enable the LDO on e07-433m20s_board (C1101 chip)
    // cc1101_en.set_high();

    // let spi_bus = Spi::new(
    //     p.SPI0, p.PIN_18, p.PIN_19, p.PIN_16, p.DMA_CH0, p.DMA_CH1, Irqs, spi_config,
    // );
    // let spi_bus = SPI_BUS.init(Mutex::new(spi_bus));
    // let mut spi_dev = SpiDevice::new(spi_bus, cs);

    // let mut btn0 = Input::new(p.PIN_22, Pull::None);

    // let gdo0 = Input::new(p.PIN_20, Pull::None);
    // let gdo2 = Input::new(p.PIN_21, Pull::None);

    // let packet = Hcs300Packet {
    //     encrypted: 0,
    //     serial_number: Hcs300SerialNumber::new(0).unwrap(),
    //     button_status: Hcs300ButtonStatus::new(0).unwrap(),
    //     vlow: false,
    //     repeat: false,
    // };
    // let mut encoded_packet = [0; Hcs300Packet::CODEWORD_BYTES];
    // packet
    //     .encode(&mut encoded_packet)
    //     .expect("Keeloq packet encoding failed!");

    // let mut cc1101 = match Cc1101::new(spi_dev, gdo0, gdo2).await {
    //     Ok(dev) => dev,
    //     Err(e) => {
    //         error!("CC1101 init failed: {:?}", e);
    //         loop {
    //             Timer::after_millis(1000).await;
    //         }
    //     }
    // };

    // let radio_config = RadioConfig::new()
    //     .frequency_hz(433_920_000)
    //     .baud_rate(2500)
    //     .modulation(Modulation::Ook)
    //     .sync_mode(SyncMode::None)
    //     .sync_word(0xD391)
    //     .packet_length(PacketLength::Fixed(Hcs300Packet::CODEWORD_BYTES as u8))
    //     .append_status(false)
    //     .crc_enable(false)
    //     .tx_power(TxPower::DbmMinus10);

    // if let Err(spi_err) = cc1101.configure(&radio_config).await {
    //     error!("SPI error during configure: {:?}", spi_err);
    //     loop {
    //         Timer::after_millis(1000).await;
    //     }
    // }

    // if let Err(err) = cc1101.idle().await {
    //     error!("Error during idle transition: {:?}", err)
    // }

    setup_pio_task_sm0(&mut pio.common, &mut pio.sm0, hcs300_pwm_pin);
    spawner.spawn(pio_task_sm0(pio.sm0).unwrap());

    loop {
        // btn0.wait_for_low().await;
        // info!("Button 0 pressed");
        // btn0.wait_for_high().await;

        //     let mut buf = [0u8; 1];
        //     spi_dev
        //         .transaction(&mut [
        //             Operation::Write(&[0x31 | 0x80 | 0x40]),
        //             Operation::Read(&mut buf),
        //         ])
        //         .await
        //         .unwrap();
        //     info!("Version number: {}", buf);
        // Timer::after_millis(100).await;
        // let test_packet = [0x55; 5];

        // Test cc1101
        // cc1101_tx_en.set_high();
        // Timer::after_millis(10).await;
        // let tx_start = Instant::now();
        // let tx_result = cc1101.transmit(&encoded_packet[..]).await;
        // info!("transmit took {} ms", tx_start.elapsed().as_millis());
        // match tx_result {
        //     Ok(()) => {
        //         info!("Keeloq packet transmitted: {=[u8]:02x}", encoded_packet[..])
        //     }
        //     Err(err) => {
        //         error!("Error during transmission: {:?}", err)
        //     }
        // }
        // Timer::after_millis(10).await;
        // cc1101_tx_en.set_low();

        // if let Err(err) = cc1101.idle().await {
        //     error!("Error during idle transition: {:?}", err)
        // }

        // Timer::after_millis(100).await;
        // cc1101_tx_en.set_low();

        Timer::after_millis(3000).await;
    }

    // Configure button pins
    // let mut btn0_pin = pins.gpio22.into_floating_input();
    // let mut btn1_pin = pins.gpio26.into_floating_input();
    // let mut btn2_pin = pins.gpio27.into_floating_input();
    // let mut btn3_pin = pins.gpio28.into_floating_input();
}
