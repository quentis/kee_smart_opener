# RAIL - SoC Empty

## Introduction

The Empty Example application is a boilerplate example which doesn't do anything
except initializes RAIL to support a Single PHY radio configuration. Also, this
example defines an empty radio event handler. These are the necessary parts what
every RAIL-based application requires.

## Prerequisites

The Empty Example application is supported on every EFR32 generations and
families that support proprietary software.

## Getting Started

Unlike the most of the available example applications in RAIL SDK, the Empty
Example does not define Command Line Interface nor does it support standard VCOM
printing or any other peripheral (LEDs/Button instances) by default.

Compile the project and download the application to a radio board. An unmodified
Empty Example shouldn't do any special:

- the radio is in idle state, while
- the MCU is running in an empty loop.

You might measure the current consumption (see the device's datasheet for the
expected active mode consumption) or debug the target device to make sure that
the example has been downloaded correctly to your device.

----

You can make the example energy friendly as simple as installing the `Power
Manager` component. Doing that the device will go to EM2 state after
initialization.

----

Adding basic packet TX/RX capabilities you might install the `Simple RAIL
Tx`/`Simple RAIL Rx` components.

## Peripherals

You can add LED and Button instances in the `Software Components` window.

To enable CLI interface you should install the `Command Line Interface (CLI)`
component. Make sure you satisfied the requirements by adding one of the `IO
Stream` dependency component, otherwise project generation will fail. If you are
working with a Silicon Labs development kit you should also ensure that the
Virtual COM port is enabled in the `Board Control` component in order to turn on
the serial bridge on the mainboard.

## Notes

> The application is designed in a way, that it can be run on an OS. You can add
> any RTOS support for this application in the `Software Components` window.
> Currently `MicriumOS` and `FreeRTOS` is supported.

## Conclusion

The `RAIL - SoC Empty` application sets up the absolute minimum to
start developing an application based on RAIL. If you want to test the basic
radio operation (packet transmission and reception) it is advised to create
`RAIL - SoC Simple TRX`.

## Resources

- [RAIL Tutorial
  Series](https://community.silabs.com/s/article/rail-tutorial-series?language=en_US):
  it is advised to read through the `Studio v5 series` first to familiarize the
  basics of packet transmission and reception.

## Report Bugs & Get Support

You are always encouraged and welcome to report any issues you found to us via
[Silicon Labs
Community](https://community.silabs.com/s/topic/0TO1M000000qHaKWAU/proprietary?language=en_US).

## Startup

HFXO Startup Time: 178us

Reference: EFR32FG23 Wireless SoC Family Data Sheet


## Retrospective

I found these functional, non-functional, DX issues during development.

Some components requires power_manager component. I suppose because power manager provides some types for baremetal.
This is problematic because you may have a project which requires no power management then adding e.g. button press component the whole project starts to use power management however button press doesn't really need power manager for its functionality. This power management requirement is even more unnecessary for RTOS project in some cases because is_ok_to_sleep isn't needed in RTOS projects.

Missing comma in macro definition in app_log:
// ARRAY DUMP
#define app_log_array_dump_level(level, p_data, len, format) \
  app_log_array_dump_level_s(level,                          \
                             APP_LOG_ARRAY_DUMP_SEPARATOR    \
                             p_data,                         \
                             len,                            \
                             format)


## Measurements

**rtl_433-rtlsdr -R help**
[131]  Microchip HCS200/HCS300 KeeLoq Hopping Encoder based remotes

**rtl_433-rtlsdr -f 433.92M -Y level=-80 -s 2048k -g 0 -R 131 -A**

Detected OOK package    2025-12-17 14:02:14
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
time      : 2025-12-17 14:02:14
model     : Microchip-HCS200                       id        : 0095D63
Battery   : 1            Button    : 1             Learn mode: 0             Repeat    : 0             encrypted : 46029991
Analyzing pulses...
Total count:   78,  width: 92.01 ms             (188429 S)
Pulse width distribution:
 [ 0] count:   35,  width:  404 us [403;406]    ( 827 S)
 [ 1] count:   43,  width:  803 us [803;804]    (1645 S)
Gap width distribution:
 [ 0] count:   53,  width:  396 us [396;397]    ( 811 S)
 [ 1] count:    1,  width: 3997 us [3997;3997]  (8185 S)
 [ 2] count:   23,  width:  796 us [795;797]    (1630 S)
Pulse period distribution:
 [ 0] count:   11,  width:  800 us [799;801]    (1638 S)
 [ 1] count:    1,  width: 4400 us [4400;4400]  (9012 S)
 [ 2] count:   65,  width: 1200 us [1200;1200]  (2457 S)
Pulse timing distribution:
 [ 0] count:   88,  width:  399 us [396;406]    ( 817 S)
 [ 1] count:   66,  width:  801 us [795;804]    (1640 S)
 [ 2] count:    1,  width: 3997 us [3997;3997]  (8185 S)
 [ 3] count:    1,  width: 10000 us [10000;10000]       (20481 S)
Level estimates [high, low]:  15931,    472
RSSI: -0.1 dB SNR: 15.3 dB Noise: -15.4 dB
Frequency offsets [F1, F2]:   18614,      0     (+581.7 kHz, +0.0 kHz)
Guessing modulation: Pulse Width Modulation with multiple packets
view at https://triq.org/pdv/#AAB0160401018E03200F9C271080808080808080808080808255+AAB04C0401018E03200F9C271081909090819090818190908181909081908190909090909090818190909081908181909090818190819081818190819081909081909090909090909090819090909355
Attempting demodulation... short_width: 404, long_width: 803, reset_limit: 3997, sync_width: 0
Use a flex decoder with -X 'n=name,m=OOK_PWM,s=404,l=803,r=3997,g=798,t=160,y=0'
[pulse_slicer_pwm] Analyzer Device
codes     : {12}fff, {66}89994062c6ba90040





Detected OOK package    2025-12-17 14:04:35
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
time      : 2025-12-17 14:04:35
model     : Microchip-HCS200                       id        : 0095D63
Battery   : 1            Button    : 1             Learn mode: 0             Repeat    : 0             encrypted : 5DC7A207
Analyzing pulses...
Total count:   78,  width: 92.01 ms             (188428 S)
Pulse width distribution:
 [ 0] count:   40,  width:  403 us [403;405]    ( 826 S)
 [ 1] count:   38,  width:  804 us [803;805]    (1646 S)
Gap width distribution:
 [ 0] count:   48,  width:  396 us [396;397]    ( 811 S)
 [ 1] count:    1,  width: 3996 us [3996;3996]  (8184 S)
 [ 2] count:   28,  width:  796 us [795;797]    (1630 S)
Pulse period distribution:
 [ 0] count:   11,  width:  800 us [800;801]    (1638 S)
 [ 1] count:    1,  width: 4399 us [4399;4399]  (9010 S)
 [ 2] count:   65,  width: 1200 us [1199;1201]  (2457 S)
Pulse timing distribution:
 [ 0] count:   88,  width:  399 us [396;405]    ( 818 S)
 [ 1] count:   66,  width:  800 us [795;805]    (1639 S)
 [ 2] count:    1,  width: 3996 us [3996;3996]  (8184 S)
 [ 3] count:    1,  width: 10000 us [10000;10000]       (20481 S)
Level estimates [high, low]:  15726,    418
RSSI: -0.2 dB SNR: 15.8 dB Noise: -15.9 dB
Frequency offsets [F1, F2]:   17155,      0     (+536.1 kHz, +0.0 kHz)
Guessing modulation: Pulse Width Modulation with multiple packets
view at https://triq.org/pdv/#AAB0160401018F03200F9C271080808080808080808080808255+AAB04C0401018F03200F9C271081818190909090909081909090819081818181909090818181908181819081908181909090818190819081818190819081909081909090909090909090819090909355
Attempting demodulation... short_width: 403, long_width: 804, reset_limit: 3997, sync_width: 0
Use a flex decoder with -X 'n=name,m=OOK_PWM,s=403,l=804,r=3997,g=798,t=160,y=0'
[pulse_slicer_pwm] Analyzer Device
codes     : {12}fff, {66}e045e3bac6ba90040

Detected OOK package    2025-12-17 14:04:35
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
time      : 2025-12-17 14:04:35
model     : Microchip-HCS200                       id        : 0095D63
Battery   : 1            Button    : 1             Learn mode: 0             Repeat    : 1             encrypted : 5DC7A207
Analyzing pulses...
Total count:   78,  width: 91.61 ms             (187609 S)
Pulse width distribution:
 [ 0] count:   41,  width:  404 us [403;405]    ( 827 S)
 [ 1] count:   37,  width:  804 us [803;805]    (1646 S)
Gap width distribution:
 [ 0] count:   48,  width:  396 us [396;397]    ( 811 S)
 [ 1] count:    1,  width: 3996 us [3996;3996]  (8184 S)
 [ 2] count:   28,  width:  796 us [795;797]    (1630 S)
Pulse period distribution:
 [ 0] count:   11,  width:  800 us [800;801]    (1638 S)
 [ 1] count:    1,  width: 4400 us [4400;4400]  (9012 S)
 [ 2] count:   65,  width: 1200 us [1199;1201]  (2457 S)
Pulse timing distribution:
 [ 0] count:   89,  width:  399 us [396;405]    ( 818 S)
 [ 1] count:   65,  width:  800 us [795;805]    (1639 S)
 [ 2] count:    1,  width: 3996 us [3996;3996]  (8184 S)
 [ 3] count:    1,  width: 10000 us [10000;10000]       (20481 S)
Level estimates [high, low]:  15846,    479
RSSI: -0.1 dB SNR: 15.2 dB Noise: -15.3 dB
Frequency offsets [F1, F2]:   19862,      0     (+620.7 kHz, +0.0 kHz)
Guessing modulation: Pulse Width Modulation with multiple packets
view at https://triq.org/pdv/#AAB0160401018F03200F9C271080808080808080808080808255+AAB04C0401018F03200F9C271081818190909090909081909090819081818181909090818181908181819081908181909090818190819081818190819081909081909090909090909090819090908355
Attempting demodulation... short_width: 404, long_width: 804, reset_limit: 3997, sync_width: 0
Use a flex decoder with -X 'n=name,m=OOK_PWM,s=404,l=804,r=3997,g=797,t=160,y=0'
[pulse_slicer_pwm] Analyzer Device
codes     : {12}fff, {66}e045e3bac6ba90044

Detected OOK package    2025-12-17 14:04:35
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
time      : 2025-12-17 14:04:35
model     : Microchip-HCS200                       id        : 0095D63
Battery   : 1            Button    : 1             Learn mode: 0             Repeat    : 1             encrypted : 5DC7A207
Analyzing pulses...
Total count:   78,  width: 91.61 ms             (187610 S)
Pulse width distribution:
 [ 0] count:   41,  width:  404 us [403;405]    ( 827 S)
 [ 1] count:   37,  width:  804 us [803;805]    (1646 S)
Gap width distribution:
 [ 0] count:   48,  width:  396 us [396;397]    ( 811 S)
 [ 1] count:    1,  width: 3997 us [3997;3997]  (8185 S)
 [ 2] count:   28,  width:  796 us [795;797]    (1630 S)
Pulse period distribution:
 [ 0] count:   11,  width:  800 us [799;802]    (1638 S)
 [ 1] count:    1,  width: 4400 us [4400;4400]  (9012 S)
 [ 2] count:   65,  width: 1200 us [1199;1201]  (2457 S)
Pulse timing distribution:
 [ 0] count:   89,  width:  399 us [396;405]    ( 818 S)
 [ 1] count:   65,  width:  800 us [795;805]    (1639 S)
 [ 2] count:    1,  width: 3997 us [3997;3997]  (8185 S)
 [ 3] count:    1,  width: 10000 us [10000;10000]       (20481 S)
Level estimates [high, low]:  15923,    235
RSSI: -0.1 dB SNR: 18.3 dB Noise: -18.4 dB
Frequency offsets [F1, F2]:   19716,      0     (+616.1 kHz, +0.0 kHz)
Guessing modulation: Pulse Width Modulation with multiple packets
view at https://triq.org/pdv/#AAB0160401018F03200F9C271080808080808080808080808255+AAB04C0401018F03200F9C271081818190909090909081909090819081818181909090818181908181819081908181909090818190819081818190819081909081909090909090909090819090908355
Attempting demodulation... short_width: 404, long_width: 804, reset_limit: 3997, sync_width: 0
Use a flex decoder with -X 'n=name,m=OOK_PWM,s=404,l=804,r=3997,g=797,t=160,y=0'
[pulse_slicer_pwm] Analyzer Device
codes     : {12}fff, {66}e045e3bac6ba90044

Detected OOK package    2025-12-17 14:04:36
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
time      : 2025-12-17 14:04:36
model     : Microchip-HCS200                       id        : 0095D63
Battery   : 1            Button    : 1             Learn mode: 0             Repeat    : 1             encrypted : 5DC7A207
Analyzing pulses...
Total count:   78,  width: 91.61 ms             (187609 S)
Pulse width distribution:
 [ 0] count:   41,  width:  403 us [403;406]    ( 826 S)
 [ 1] count:   37,  width:  803 us [803;805]    (1645 S)
Gap width distribution:
 [ 0] count:   48,  width:  396 us [396;397]    ( 811 S)
 [ 1] count:    1,  width: 3997 us [3997;3997]  (8185 S)
 [ 2] count:   28,  width:  796 us [795;797]    (1630 S)
Pulse period distribution:
 [ 0] count:   11,  width:  800 us [800;802]    (1638 S)
 [ 1] count:    1,  width: 4400 us [4400;4400]  (9011 S)
 [ 2] count:   65,  width: 1200 us [1199;1201]  (2457 S)
Pulse timing distribution:
 [ 0] count:   89,  width:  399 us [396;406]    ( 818 S)
 [ 1] count:   65,  width:  800 us [795;805]    (1639 S)
 [ 2] count:    1,  width: 3997 us [3997;3997]  (8185 S)
 [ 3] count:    1,  width: 10000 us [10000;10000]       (20481 S)
Level estimates [high, low]:  15648,     77
RSSI: -0.2 dB SNR: 23.1 dB Noise: -23.3 dB
Frequency offsets [F1, F2]:   17343,      0     (+542.0 kHz, +0.0 kHz)
Guessing modulation: Pulse Width Modulation with multiple packets
view at https://triq.org/pdv/#AAB0160401018F03200F9C271080808080808080808080808255+AAB04C0401018F03200F9C271081818190909090909081909090819081818181909090818181908181819081908181909090818190819081818190819081909081909090909090909090819090908355
Attempting demodulation... short_width: 403, long_width: 803, reset_limit: 3997, sync_width: 0
Use a flex decoder with -X 'n=name,m=OOK_PWM,s=403,l=803,r=3997,g=797,t=160,y=0'
[pulse_slicer_pwm] Analyzer Device
codes     : {12}fff, {66}e045e3bac6ba90044

Detected OOK package    2025-12-17 14:04:36
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
time      : 2025-12-17 14:04:36
model     : Microchip-HCS200                       id        : 0095D63
Battery   : 1            Button    : 1             Learn mode: 0             Repeat    : 1             encrypted : 5DC7A207
Analyzing pulses...
Total count:   78,  width: 91.61 ms             (187608 S)
Pulse width distribution:
 [ 0] count:   41,  width:  403 us [402;406]    ( 826 S)
 [ 1] count:   37,  width:  803 us [802;804]    (1645 S)
Gap width distribution:
 [ 0] count:   48,  width:  396 us [396;397]    ( 812 S)
 [ 1] count:    1,  width: 3997 us [3997;3997]  (8186 S)
 [ 2] count:   28,  width:  796 us [795;797]    (1631 S)
Pulse period distribution:
 [ 0] count:   11,  width:  800 us [800;802]    (1638 S)
 [ 1] count:    1,  width: 4400 us [4400;4400]  (9011 S)
 [ 2] count:   65,  width: 1200 us [1199;1201]  (2457 S)
Pulse timing distribution:
 [ 0] count:   89,  width:  399 us [396;406]    ( 818 S)
 [ 1] count:   65,  width:  800 us [795;804]    (1639 S)
 [ 2] count:    1,  width: 3997 us [3997;3997]  (8186 S)
 [ 3] count:    1,  width: 10000 us [10000;10000]       (20481 S)
Level estimates [high, low]:  15731,     52
RSSI: -0.2 dB SNR: 24.8 dB Noise: -25.0 dB
Frequency offsets [F1, F2]:   17112,      0     (+534.8 kHz, +0.0 kHz)
Guessing modulation: Pulse Width Modulation with multiple packets
view at https://triq.org/pdv/#AAB0160401018F03200F9D271080808080808080808080808255+AAB04C0401018F03200F9D271081818190909090909081909090819081818181909090818181908181819081908181909090818190819081818190819081909081909090909090909090819090908355
Attempting demodulation... short_width: 403, long_width: 803, reset_limit: 3998, sync_width: 0
Use a flex decoder with -X 'n=name,m=OOK_PWM,s=403,l=803,r=3998,g=798,t=160,y=0'
[pulse_slicer_pwm] Analyzer Device
codes     : {12}fff, {66}e045e3bac6ba90044