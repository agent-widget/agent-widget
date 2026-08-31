> Chinese version: [board-spec-constraints.zh-CN.md](./board-spec-constraints.zh-CN.md)

# Waveshare ESP32-S3-Touch-LCD-3.5B Board Specifications and Hard Constraints

> Status: authoritative (verified item by item on 2026-08-24 against the official Wiki / docs platform / product page / official demo repository source)
> This file is the single source of hardware truth for development and simulation. When it conflicts with older documents, this file wins; when real-device measurements (AW-002/003) find discrepancies, update this file with evidence.

## 1. Board Identification

| Item | Value |
|---|---|
| SKU | 31137 (3.5B); 31334 (3.5B-C, with enclosure + OV5640 camera) |
| SoC | ESP32-S3R8 (Xtensa LX7 dual-core 240MHz) |
| RAM | 512KB SRAM + 384KB ROM + **8MB stacked Octal PSRAM** |
| Flash | **16MB** W25Q128JVSIQ NOR Flash, **QIO** mode |
| Wireless | 2.4GHz Wi-Fi (802.11 b/g/n) + Bluetooth 5 LE, onboard antenna (external IPEX1 requires re-soldering a resistor) |

## 2. Display (hard constraint, do not misconfigure)

| Item | Value |
|---|---|
| Panel | 3.5-inch IPS capacitive touch, **320×480 portrait (native)**, 262K colors |
| Brightness / contrast | 210 cd/m² / 1000:1 |
| Driver IC | **AXS15231B** (combined display QSPI + touch I2C) |
| Display interface | **QSPI (4-bit)**, SPI2_HOST, pclk **40MHz** |
| Pixel format | RGB565 (16bpp), RGB element order |
| Pins | CS=12, SCLK=5, D0=1, D1=2, D2=3, D3=4 |
| Backlight | GPIO6 (LEDC 5kHz, 10-bit PWM) |
| Reset | **RST=NC**: driven by a reset pulse (0→100ms→1) output on P1.0 of the TCA9554 I/O expander (0x20); the pulse must be issued before initializing the display |

Key points of the official initialization (ESP-IDF BSP):

```c
spi_bus_config_t buscfg = { .sclk_io_num = 5, .data0_io_num = 1,
                            .data1_io_num = 2, .data2_io_num = 3, .data3_io_num = 4,
                            .max_transfer_sz = max_transfer_sz };
spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO);
// io_config = AXS15231B_PANEL_IO_QSPI_CONFIG(12, NULL, NULL); io_config.pclk_hz = 40MHz
// panel: 16bpp, RGB order; vendor flags.use_qspi_interface = 1
```

Equivalent Arduino code: `new Arduino_ESP32QSPI(12, 5, 1, 2, 3, 4)` + `new Arduino_AXS15231B(bus, -1, 0, false, 320, 480)`, with `GFX_BL = 6`.

## 3. Touch (hard constraint, do not misconfigure)

| Item | Value |
|---|---|
| Controller | **AXS15231B integrated touch** (not FT6336U / CST816 / GT911) |
| Interface | I2C, address **0x3B**, 400kHz |
| Touch points | Up to 2 points |
| INT / RST | Both unconnected (GPIO_NUM_NC) |
| Read protocol | 11-byte command `{0xb5,0xab,0xa5,0x5a,0x00,0x00,0x00,0x0e,0x00,0x00,0x00}`, reads back 14 bytes; coordinates are parsed from data[2..5] (and data[8..11] for the second point); see the official `bsp_touch.c` |
| Coordinate system | Direct 320×480 mapping at rotation 0, no swap/mirror |

## 4. I2C Bus (single bus, SDA=8 / SCL=7, port 0, 400kHz, internal pull-ups)

| Device | 7-bit address | Purpose |
|---|---|---|
| TCA9554 | **0x20** | I/O expansion: LCD reset (P1.0), PWR key detection (EXIO6), etc. |
| AXP2101 | **0x34** | PMIC: battery charge/discharge, multiple power rails, fuel-gauge/voltage ADC |
| QMI8658 | **0x6B** | 6-axis IMU (accelerometer + gyroscope) |
| PCF85063 | **0x51** | RTC (powered by AXP2101; keeps time across power loss) |
| ES8311 | **0x18** | Audio codec (onboard microphone + MX1.25 speaker, I2S data) |
| AXS15231B | **0x3B** | Touch |

The camera SCCB shares the same bus (SIOD=8 / SIOC=7).

> ⚠️ Six devices plus the camera share one I2C bus; multi-task access must use a mutex (the official BSP uses the recursive mutex bsp_i2c_mux).

## 5. Other Peripheral Pins

| Peripheral | Pins |
|---|---|
| SD card (SDMMC, **1-bit**) | CLK=11, CMD=10, D0=9 |
| Camera DVP | XCLK=38, Y9=21, Y8=39, Y7=40, Y6=42, Y5=46, Y4=48, Y3=47, Y2=45, VSYNC=17, HREF=18, PCLK=41, PWDN/RESET=-1 |
| BOOT key | GPIO0 (active low; hold while powering on to enter download mode) |
| PWR key | Via TCA9554 (single press powers on; programmable in normal state; hold 6s to power off) |
| RESET key | Hardware reset |
| Battery | MX1.25 2P 3.7V lithium (AXP2101 charge/discharge) |
| RTC backup | SH1.0 |

## 6. Toolchain and Build Configuration Constraints

- **ESP-IDF**: the official demo requires ≥5.1 and the Wiki tutorial is written against ≥5.4 → this project pins **≥5.4** (AW-002 records the exact version).
- **Arduino**: esp32 core ≥3.2.0; the partition scheme **must be "16M Flash(3MB APP/9.9MB FATFS)"** or a custom 16MB partition table; serial printing requires **USB CDC On Boot** (Type-C is the ESP32-S3 native USB, not an external UART bridge).
- Key sdkconfig (official demo values; do not change casually):

```ini
CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y
CONFIG_ESPTOOLPY_FLASHMODE_QIO=y
CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_OCT=y      ; 8MB Octal PSRAM
CONFIG_SPIRAM_SPEED_80M=y
CONFIG_LV_COLOR_16_SWAP=y     ; RGB565 byte swap (required by LVGL **v8.4** flush; v9.x has no such macro — the display driver's color format handles it; AW-005 confirms per the chosen version)
```

- Official component dependencies (`idf_component.yml`): `espressif/esp_lcd_axs15231b ^1.0.0`, `espressif/esp_io_expander_tca9554 ^2.0.0`, `espressif/esp_codec_dev ^1.3.4`, `espressif/button ^4.1.0`, `lvgl/lvgl ~8.4.0`.
- LVGL version: the official Arduino demo supports **v8.4.0 or v9.2.2**; this repository's PC simulator uses **LVGL 9.6**. The production firmware version must be locked in AW-005 and recorded in the UI docs (align with the sim by choosing v9.x, or align with the official demo by choosing v8.4 — pick one; mixing APIs is forbidden).
- LVGL memory baseline (official factory): LV_MEM_SIZE 48KB; display buffer is a **full-screen PSRAM buffer (320×480×2 = 300KB, buff_spiram=true)** + LVGL flush trans_size = 1/10 screen; LVGL task on core 1, priority 4, 5KB stack, 5ms timer.
- Flashing: Type-C native USB + onboard auto-download circuit (no manual BOOT needed); if the program crashes, hold BOOT while powering on to force download mode.

## 7. Partition Table Constraints (critical for the OTA task AW-006)

- The official demo partition table has **only factory (6M, offset 0x10000) + nvs (0x6000) + phy_init** and **no dual OTA slots**.
- This project's OTA goal needs a custom partition table with **factory + ota_0 + ota_1 (dual OTA app partitions + otadata)**; the table must be frozen and committed under `firmware/` before AW-002 real-device verification.
- See the conclusion in [04-ota-evaluation-conclusion.md](../ota/04-ota-evaluation-conclusion.md): nvs should be enlarged to 0x8000 (OTA resume + Wi-Fi state), and storage uses LittleFS.

## 8. Simulator Correspondence Rules (the PC sim must not violate these)

1. Resolution **320×480 portrait** and **RGB565 16bpp** — the sim must match (the current `sim/lvgl-sim` already does).
2. Touch: 2 capacitive points → the sim must support at least single-point dragging; coordinates are **not rotated** (ROT 0), so the sim's touch orientation must match the device.
3. **Performance conclusions are only valid on real hardware**: frame rate, touch latency, memory/PSRAM, Wi-Fi reconnection, OTA rollback. The sim only verifies layout, swipe rules, status mapping, and interaction semantics.
4. Do not assume QSPI 40MHz refresh bandwidth, PSRAM size, or DMA behavior just because the sim is smooth; do not substitute sim conclusions for real-device acceptance.
5. Chinese fonts: the device must embed fonts (LVGL font conversion); the sim's PC fonts are only for layout reference.

## 9. Common Mistake Look-Up (checklist to prevent misconfiguration)

| Wrong approach | Correct approach |
|---|---|
| Using a ST7796 / Arduino_TFT / single-line SPI driver | AXS15231B **QSPI** (4-bit) |
| Using FT6336U / CST816 / GT911 touch drivers | AXS15231B touch, I2C **0x3B** |
| Designing the UI as 480×320 landscape | 320×480 native portrait, ROT 0 |
| Using an 8MB or default partition table / 4MB partitions | 16MB QIO + custom partition table |
| Connecting LCD RST to some GPIO | RST=NC; use the TCA9554 P1.0 reset pulse |
| Using SPI1/SPI3 or FSPI default pins | SPI2_HOST + the fixed pins above |
| Initializing the display without the TCA9554 reset pulse | Must pulse first (0→100ms→1) |
| Copying over non-B (ESP32-S3-Touch-LCD-3.5) pins/drivers | Always defer to this file |

## 10. Sources (verified 2026-08-24)

- Wiki: https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B
- Docs platform: https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B
- Product page: https://www.waveshare.com/product/esp32-s3-touch-lcd-3.5b.htm
- Official demo repository: https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.5B
  - `Arduino/examples/08_gfx_helloworld`, `09_lvgl_arduino_v8` (QSPI pins, BL=6, TCA9554)
  - `ESP-IDF/01_factory/components/esp_bsp/` (bsp_display/bsp_touch/bsp_i2c/bsp_sdcard/bsp_camera/bsp_axp2101, etc.)
  - `ESP-IDF/01_factory/sdkconfig.defaults`, `partitions.csv`, `main/idf_component.yml`
- Datasheets (Wiki Resources → Datasheets): AXS15231B, ESP32-S3 Series Datasheet, etc.
