---
title: "Development Environment Setup"
date: 2026-08-21
status: complete
tags:
  - esp32
  - arduino
  - esp-idf
description: "ESP32-S3-Touch-LCD-3.5B development environment: Arduino IDE / ESP-IDF / flashing and LVGL configuration"
---
> Chinese version: [dev-environment.zh-CN.md](./dev-environment.zh-CN.md)


# Development Environment Setup

> Created: 2026-08-21

---

## Two Official Development Paths

| Path | Learning curve | Suitable for | Dependencies |
|---|---|---|---|
| **Arduino IDE** | Gentle | Rapid prototyping, HMI demos, sensor demos | arduino-esp32 core + libraries |
| **ESP-IDF** | Steep | Production-grade, performance-sensitive, complex systems | ESP-IDF **≥5.4** + VS Code extension |

> ⚠️ **Path boundary (updated 2026-08-24)**: this project's production firmware target is **ESP-IDF** (see the project's operating contract and `docs/hardware/board-spec-constraints.md`). The Arduino path is only historical PoC / rapid-prototyping reference and **must not** be migrated into `firmware/`. The Arduino section below flags the corresponding constraints for comparison only.

## 1. Arduino IDE Path

### 1.1 Install ESP32 board support

1. Arduino IDE → File → Preferences → Additional boards manager URLs, add:
   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```
2. Tools → Board → Boards Manager → search for "esp32" → install **esp32 by Espressif Systems**
3. Select the board: Tools → Board → **ESP32S3 Dev Module** (or "Waveshare ESP32-S3" if listed)

### 1.2 Install the required libraries

| Library | Purpose | Installation |
|---|---|---|
| **Arduino_GFX** | Display driver (QSPI + AXS15231B) | Search "Arduino_GFX by moononournation" in the Library Manager |
| **LVGL** (optional, for GUI) | GUI framework | Download from [lvgl/lvgl GitHub](https://github.com/lvgl/lvgl) or use the Library Manager (mind the version) |
| **lv_conf.h** | LVGL configuration | Copy `lv_conf_template.h` → `lv_conf.h`, set `LV_COLOR_DEPTH 16` and `LV_MEM_SIZE` |
| **TFT_eSPI** (alternative, for the regular version) | Another display driver | Library Manager (Type B normally just uses Arduino_GFX) |

> ⚠️ **Version pitfall**: the official demo uses LVGL **v8.4.0**. LVGL v9 changed the API significantly (`lv_disp_drv_t`→`lv_display_t`, `lv_scr_act()`→`lv_screen_active()`), and mixing versions from online tutorials will fail to compile. **Start with the official demo's version, then decide about upgrading.**

### 1.3 Initialize display + touch (core code skeleton)

```cpp
#include <Arduino_GFX_Library.h>

// QSPI bus (Type B pins)
Arduino_DataBus *bus = new Arduino_ESP32QSPI(
    12 /*CS*/, 5 /*CLK*/, 1 /*D0*/, 2 /*D1*/, 3 /*D2*/, 4 /*D3*/);

// Display object
Arduino_GFX *g = new Arduino_AXS15231B(bus, -1, 0, false, 320, 480);
Arduino_Canvas *gfx = new Arduino_Canvas(320, 480, g, 0, 0, 0 /*ROTATION*/); // ROT 0: 320×480 native portrait, no rotation

void setup() {
  gfx->begin();
  gfx->fillScreen(BLACK);
}
```

Touch (**AXS15231B integrated touch, I2C 0x3B**, up to 2 points): the official demo wraps it in the LVGL example (the `touchpad_read` callback). ⚠️ It is NOT FT6336U/0x38 (that is the regular 3.5 version's touch). Before initializing the display, a reset pulse (0→100ms→1) must be output on P1.0 of the TCA9554 (I2C 0x20); backlight uses GPIO6.

### 1.4 LVGL + Arduino integration skeleton

```cpp
#include <lvgl.h>
#include <Arduino_GFX_Library.h>

static lv_disp_draw_buf_t draw_buf;
static lv_color_t buf[320 * 480 / 10];   // 1/10 screen buffer; larger is fine with PSRAM

void my_disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
  gfx->draw16bitBeRGBBitmap(area->x1, area->y1, (uint16_t*)color_p,
                            area->x2 - area->x1 + 1, area->y2 - area->y1 + 1);
  lv_disp_flush_ready(disp);
}

void my_touchpad_read(lv_indev_drv_t *indev, lv_indev_data_t *data) {
  // Read coordinates from the AXS15231B (I2C 0x3B), fill data->point.x / data->point.y,
  // set data->state = LV_INDEV_STATE_PRESSED
}

void setup() {
  lv_init();
  lv_disp_draw_buf_init(&draw_buf, buf, NULL, 320 * 480 / 10);
  static lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = 320; disp_drv.ver_res = 480;
  disp_drv.flush_cb = my_disp_flush;
  lv_disp_drv_register(&disp_drv);
  // ... touch registration
  // Build the UI (see data-viz-diagram-design.md)
}

void loop() {
  lv_timer_handler();
  delay(5);
}
```

## 2. ESP-IDF Path (summary)

1. Install [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/) (**≥5.4**) + the VS Code **Espressif IDF extension**; target `esp32s3`, 16MB QIO Flash, Octal PSRAM at 80MHz, `CONFIG_LV_COLOR_16_SWAP=y` (see `docs/hardware/board-spec-constraints.md`)
2. `F1` → `ESP-IDF: Show Examples Projects` → pick the official demo (e.g. `esp32-s3-lcd-3.5B`)
3. Select the COM port → Build → Flash → Monitor (the one-click "little flame")
4. Official components: `waveshareteam/Waveshare-ESP32-components` (ESP Component Registry), including the AXS15231B driver, LVGL bindings, etc.

## 3. Flashing Notes

- Connect via Type-C; the onboard auto-download circuit handles it (no manual BOOT press needed)
- If flashing fails: hold RESET for >1 second or enter download mode, wait for the system to re-enumerate the COM port, then retry
- The first ESP-IDF build is slow (saturating the CPU is normal)

## 4. Official Demo Repositories

- **Waveshare official demo** (download from the Wiki; two directories, Arduino/ and ESP-IDF/)
- **Waveshare-ESP32-components** (GitHub, componentized drivers) → https://github.com/waveshareteam/Waveshare-ESP32-components
- **Community reference**: paulhamsh/Waveshare-ESP32-S3-LCD-7-LVGL (an LVGL v9 porting example; borrow the structure)

---

## Sources

- [Waveshare official docs - Working with Arduino](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B/Arduino)
- [Waveshare Wiki - ESP-IDF development](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B)
- [arduino-esp32 GitHub](https://github.com/espressif/arduino-esp32)
- [waveshareteam/Waveshare-ESP32-components](https://github.com/waveshareteam/Waveshare-ESP32-components)
- [LVGL GitHub](https://github.com/lvgl/lvgl)
