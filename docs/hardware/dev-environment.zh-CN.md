---
title: "开发环境搭建"
date: 2026-08-21
status: complete
tags:
  - esp32
  - arduino
  - esp-idf
description: "ESP32-S3-Touch-LCD-3.5B 开发环境：Arduino IDE / ESP-IDF / 烧录与 LVGL 配置"
---
> English version: [dev-environment.md](./dev-environment.md)


# 开发环境搭建

> 创建时间: 2026-08-21

---

## 两条官方开发路径

| 路径 | 学习曲线 | 适合场景 | 依赖 |
|---|---|---|---|
| **Arduino IDE** | 平缓 | 快速原型、HMI demo、传感器展示 | arduino-esp32 core + 库 |
| **ESP-IDF** | 陡峭 | 生产级、性能敏感、复杂系统 | ESP-IDF **≥5.4** + VS Code 插件 |

> ⚠️ **路线边界（2026-08-24 更新）**：本项目正式固件目标是 **ESP-IDF**（见项目操作契约与 `docs/hardware/board-spec-constraints.md`）。Arduino 路线仅作历史 PoC / 快速原型参考，**不得**迁移进 `firmware/`。本文 Arduino 段落标注了对应约束，仅供对照。

## 一、Arduino IDE 路线

### 1. 安装 ESP32 板支持

1. Arduino IDE → 文件 → 首选项 → 附加开发板管理器地址，添加：
   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```
2. 工具 → 开发板 → 开发板管理器 → 搜索 "esp32" → 安装 **esp32 by Espressif Systems**
3. 选板：工具 → 开发板 → **ESP32S3 Dev Module**（或 "Waveshare ESP32-S3" 若列表有）

### 2. 安装所需库

| 库 | 用途 | 安装方式 |
|---|---|---|
| **Arduino_GFX** | 显示驱动（QSPI + AXS15231B）| 库管理器搜索 "Arduino_GFX by moononournation" |
| **LVGL**（可选，做 GUI）| 图形界面框架 | 从 [lvgl/lvgl GitHub](https://github.com/lvgl/lvgl) 下载，或用库管理器（注意版本）|
| **lv_conf.h** | LVGL 配置 | 复制 `lv_conf_template.h` → `lv_conf.h`，改 `LV_COLOR_DEPTH 16`、`LV_MEM_SIZE` |
| **TFT_eSPI**（备选，普通版用）| 另一种显示驱动 | 库管理器（Type B 一般用 Arduino_GFX 即可）|

> ⚠️ **版本坑**：官方 demo 用 LVGL **v8.4.0**。LVGL v9 API 大改（`lv_disp_drv_t`→`lv_display_t`，`lv_scr_act()`→`lv_screen_active()`），网上教程混用版本会编译失败。**先用官方 demo 的版本，再决定升级**。

### 3. 初始化显示 + 触摸（核心代码骨架）

```cpp
#include <Arduino_GFX_Library.h>

// QSPI 总线（Type B 引脚）
Arduino_DataBus *bus = new Arduino_ESP32QSPI(
    12 /*CS*/, 5 /*CLK*/, 1 /*D0*/, 2 /*D1*/, 3 /*D2*/, 4 /*D3*/);

// 显示对象
Arduino_GFX *g = new Arduino_AXS15231B(bus, -1, 0, false, 320, 480);
Arduino_Canvas *gfx = new Arduino_Canvas(320, 480, g, 0, 0, 0 /*ROTATION*/); // ROT 0：320×480 竖屏原生，不旋转

void setup() {
  gfx->begin();
  gfx->fillScreen(BLACK);
}
```

触摸（**AXS15231B 一体触摸，I2C 0x3B**，最多 2 点）：官方 demo 封装在 LVGL 示例里（`touchpad_read` 回调）。⚠️ 不是 FT6336U/0x38（那是普通版 3.5 的触摸）。显示初始化前必须先经 TCA9554（I2C 0x20）P1.0 输出复位脉冲（0→100ms→1），背光用 GPIO6。

### 4. LVGL + Arduino 集成骨架

```cpp
#include <lvgl.h>
#include <Arduino_GFX_Library.h>

static lv_disp_draw_buf_t draw_buf;
static lv_color_t buf[320 * 480 / 10];   // 1/10 屏缓冲，PSRAM 够可更大

void my_disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
  gfx->draw16bitBeRGBBitmap(area->x1, area->y1, (uint16_t*)color_p,
                            area->x2 - area->x1 + 1, area->y2 - area->y1 + 1);
  lv_disp_flush_ready(disp);
}

void my_touchpad_read(lv_indev_drv_t *indev, lv_indev_data_t *data) {
  // 从 AXS15231B（I2C 0x3B）读坐标，填入 data->point.x / data->point.y，data->state = LV_INDEV_STATE_PRESSED
}

void setup() {
  lv_init();
  lv_disp_draw_buf_init(&draw_buf, buf, NULL, 320 * 480 / 10);
  static lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = 320; disp_drv.ver_res = 480;
  disp_drv.flush_cb = my_disp_flush;
  lv_disp_drv_register(&disp_drv);
  // ... touch 注册
  // 建 UI（见 data-viz-diagram-design.md）
}

void loop() {
  lv_timer_handler();
  delay(5);
}
```

## 二、ESP-IDF 路线（简述）

1. 安装 [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/)（**≥5.4**）+ VS Code **Espressif IDF 插件**；目标 `esp32s3`，16MB QIO Flash、Octal PSRAM 80MHz、`CONFIG_LV_COLOR_16_SWAP=y`（详见 `docs/hardware/board-spec-constraints.md`）
2. `F1` → `ESP-IDF: Show Examples Projects` → 选官方 demo（如 `esp32-s3-lcd-3.5B`）
3. 选 COM 口 → Build → Flash → Monitor（"小火焰"一键）
4. 官方组件：`waveshareteam/Waveshare-ESP32-components`（ESP Component Registry），含 AXS15231B 驱动、LVGL 绑定等

## 三、烧录注意

- Type-C 连接，板载自动下载电路（无需手动按 BOOT）
- 若烧录失败：按住 RESET >1 秒或进下载模式，等系统重新识别 COM 口再试
- 首次编译 ESP-IDF 很慢（占满 CPU 属正常）

## 四、官方 demo 仓库

- **Waveshare 官方 demo**（Wiki 提供下载，Arduino/ 和 ESP-IDF/ 两个目录）
- **Waveshare-ESP32-components**（GitHub，组件化驱动）→ https://github.com/waveshareteam/Waveshare-ESP32-components
- **社区参考**：paulhamsh/Waveshare-ESP32-S3-LCD-7-LVGL（LVGL v9 移植示例，可借鉴结构）

---

## 引用来源

- [Waveshare 官方文档 - Working with Arduino](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B/Arduino)
- [Waveshare Wiki - ESP-IDF 开发](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B)
- [arduino-esp32 GitHub](https://github.com/espressif/arduino-esp32)
- [waveshareteam/Waveshare-ESP32-components](https://github.com/waveshareteam/Waveshare-ESP32-components)
- [LVGL GitHub](https://github.com/lvgl/lvgl)
