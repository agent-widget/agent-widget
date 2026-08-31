---
title: "Hardware Specifications and Pinout"
date: 2026-08-21
status: complete
tags:
  - esp32
  - hardware
description: "ESP32-S3-Touch-LCD-3.5B hardware specifications, onboard peripherals, QSPI pin definitions, and differences from the regular version"
---
> Chinese version: [hardware-spec.zh-CN.md](./hardware-spec.zh-CN.md)


> ⚠️ **2026-08-24 update**: this document is a research note; the **authoritative constraint list is [board-spec-constraints.md](./board-spec-constraints.md)** (all pins, I2C addresses, build configuration, and simulator rules). In case of conflict, board-spec-constraints.md wins.

# Hardware Specifications and Pinout

> Created: 2026-08-21

---

## Core Specifications

| Item | Specification |
|---|---|
| SKU | 31137 (3.5B), 31334 (3.5B-C with enclosure) |
| SoC | ESP32-S3R8 (Xtensa LX7 dual-core, 240MHz) |
| RAM | 512KB SRAM + **8MB stacked PSRAM** |
| Flash | **16MB** (W25Q128JVSIQ NOR Flash) |
| Wireless | 2.4GHz Wi-Fi (802.11 b/g/n) + Bluetooth 5 LE (onboard antenna; external IPEX1 optional) |
| Screen | 3.5-inch capacitive-touch IPS, **320×480**, 262K colors |
| Display driver | **AXS15231B** (QSPI + I2C communication) |
| Touch controller | **AXS15231B integrated capacitive touch (I2C 0x3B)** (⚠️ not FT6336U; FT6336U is the regular 3.5 version's touch) |
| Connectors | Type-C (power + flashing), TF card slot, camera connector (OV5640/OV2640), MX1.25 speaker/battery, SH1.0 RTC battery, 2.54mm GPIO headers |

## Onboard Peripherals

| Chip | Function |
|---|---|
| AXP2101 | Power management: multiple outputs, lithium battery charge/discharge (3.7V MX1.25), battery lifetime optimization |
| QMI8658 | 6-axis IMU (3-axis accelerometer + 3-axis gyroscope); usable for orientation/step counting |
| PCF85063 | RTC clock chip (powered by AXP2101; keeps time across power loss) |
| ES8311 | Low-power audio codec (onboard microphone + speaker connector) |
| W25Q128JVSIQ | 16MB NOR Flash |

Keys: three side keys — PWR, BOOT, RESET (PWR/BOOT functions are programmable).

## Display Interface (QSPI Pin Definitions)

Type B uses **QSPI** (4-bit parallel SPI) at a 40MHz clock. Pins (confirmed from lvgl-micropython issue #530 and the official BSP):

| Signal | GPIO |
|---|---|
| LCD_CS | GPIO 12 |
| LCD_CLK (SCLK) | GPIO 5 |
| LCD_D0 | GPIO 1 |
| LCD_D1 | GPIO 2 |
| LCD_D2 | GPIO 3 |
| LCD_D3 | GPIO 4 |
| LCD_BL (backlight) | GPIO 6 |
| DC | None (QSPI needs no DC line) |

> ⚠️ Note: the regular ESP32-S3-Touch-LCD-3.5 (non-B) uses SPI + the ST7796 driver + FT6336U touch, with completely different pins. **Type B demo code commonly uses the `Arduino_ESP32QSPI` bus + the `Arduino_AXS15231B` display class**; the touch is also AXS15231B (I2C 0x3B, not FT6336U).

## Board-Level I2C Bus (SDA=GPIO8 / SCL=GPIO7, 400kHz)

| Device | Address | Purpose |
|---|---|---|
| TCA9554 | 0x20 | I/O expansion (LCD reset P1.0, PWR key) |
| AXP2101 | 0x34 | PMIC / battery |
| QMI8658 | 0x6B | 6-axis IMU |
| PCF85063 | 0x51 | RTC |
| ES8311 | 0x18 | Audio codec |
| AXS15231B | 0x3B | Touch |

SD card (SDMMC 1-bit): CLK=11 / CMD=10 / D0=9. Camera DVP: XCLK=38, Y9..Y2=21,39,40,42,46,48,47,45, VSYNC=17, HREF=18, PCLK=41.

## Arduino Initialization Code (Official)

```cpp
Arduino_DataBus *bus = new Arduino_ESP32QSPI(LCD_QSPI_CS, LCD_QSPI_CLK, LCD_QSPI_D0, LCD_QSPI_D1, LCD_QSPI_D2, LCD_QSPI_D3);
Arduino_GFX *g = new Arduino_AXS15231B(bus, -1, 0, false, 320, 480);
Arduino_Canvas *gfx = new Arduino_Canvas(320, 480, g, 0, 0, ROTATION);
```

## Quick Differences from the Regular (Non-B) Version

| | ESP32-S3-Touch-LCD-3.5 | **3.5B (this document)** |
|---|---|---|
| Display driver | ST7796 (SPI) | AXS15231B (QSPI) |
| Refresh bandwidth | Lower | **Higher (QSPI 4-bit)** |
| Pins | Standard SPI pins | QSPI D0-D3 |
| Other | — | Extra microphone/speaker/camera connectors |

## My Analysis

- **The 8MB PSRAM is key for data visualization**: a large LVGL draw buffer (up to 1/4 screen) + chart data caches + Wi-Fi buffers all fit without tight budgeting
- QSPI refreshes roughly 4x faster than SPI, making LVGL animations/chart updates smoother; however, **community material is scarcer than for the regular version**, so search tutorials with "3.5B" or "AXS15231B" keywords
- Onboard IMU + RTC + audio makes an all-in-one "environmental data collection + display" device easy (sensor data → charts) without external modules

---

## Sources

- [Waveshare official docs platform](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B) | Official documentation
- [Waveshare Wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B) | Official wiki
- [lvgl-micropython issue #530](https://github.com/lvgl-micropython/lvgl_micropython/issues/530) | QSPI pin reference
