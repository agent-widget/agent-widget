---
title: "硬件规格与引脚"
date: 2026-08-21
status: complete
tags:
  - esp32
  - hardware
description: "ESP32-S3-Touch-LCD-3.5B 硬件规格、板载外设、QSPI 引脚定义、与普通版差异"
---
> English version: [hardware-spec.md](./hardware-spec.md)


> ⚠️ **2026-08-24 更新**：本文档为研究笔记；**权威约束清单见 [board-spec-constraints.md](./board-spec-constraints.md)**（含全部引脚、I2C 地址、构建配置与模拟器规则）。若有冲突以 board-spec-constraints.md 为准。

# 硬件规格与引脚

> 创建时间: 2026-08-21

---

## 核心规格

| 项目 | 规格 |
|---|---|
| SKU | 31137（3.5B）、31334（3.5B-C 带外壳版）|
| SoC | ESP32-S3R8（Xtensa LX7 双核，240MHz）|
| RAM | 512KB SRAM + **8MB 堆叠 PSRAM** |
| Flash | **16MB**（W25Q128JVSIQ NOR-Flash）|
| 无线 | 2.4GHz Wi-Fi (802.11 b/g/n) + Bluetooth 5 LE（板载天线，IPEX1 外接可选）|
| 屏幕 | 3.5inch 电容触摸 IPS，**320×480**，262K 色 |
| 显示驱动 | **AXS15231B**（QSPI + I2C 通信）|
| 触摸芯片 | **AXS15231B 一体电容触摸（I2C 0x3B）**（⚠️ 不是 FT6336U；FT6336U 是普通版 3.5 的触摸）|
| 接口 | Type-C（供电+烧录）、TF 卡槽、摄像头接口（OV5640/OV2640）、MX1.25 喇叭/电池、SH1.0 RTC 电池、2.54mm GPIO 排针 |

## 板载外设

| 芯片 | 功能 |
|---|---|
| AXP2101 | 电源管理：多路输出、锂电池充放电（3.7V MX1.25）、电池寿命优化 |
| QMI8658 | 6 轴 IMU（3 轴加速度计 + 3 轴陀螺仪），可做姿态/计步 |
| PCF85063 | RTC 时钟芯片（AXP2101 供电，断电不掉时间）|
| ES8311 | 低功耗音频 codec（板载麦克风 + 喇叭接口）|
| W25Q128JVSIQ | 16MB NOR Flash |

按键：PWR、BOOT、RESET 三颗侧键（PWR/BOOT 可自定义功能）。

## 显示接口（QSPI 引脚定义）

Type B 用 **QSPI**（4-bit 并行 SPI）驱动，40MHz 时钟。引脚（从 lvgl-micropython issue #530 和官方 BSP 确认）：

| 信号 | GPIO |
|---|---|
| LCD_CS | GPIO 12 |
| LCD_CLK (SCLK) | GPIO 5 |
| LCD_D0 | GPIO 1 |
| LCD_D1 | GPIO 2 |
| LCD_D2 | GPIO 3 |
| LCD_D3 | GPIO 4 |
| LCD_BL（背光） | GPIO 6 |
| DC | 无（QSPI 无需 DC 线）|

> ⚠️ 注意：普通版 ESP32-S3-Touch-LCD-3.5（非 B）用 SPI + ST7796 驱动 + FT6336U 触摸，引脚完全不同。**Type B 的 demo 代码里常见 `Arduino_ESP32QSPI` 总线 + `Arduino_AXS15231B` 显示类**；触摸也是 AXS15231B（I2C 0x3B，非 FT6336U）。

## 板级 I2C 总线（SDA=GPIO8 / SCL=GPIO7，400kHz）

| 器件 | 地址 | 用途 |
|---|---|---|
| TCA9554 | 0x20 | IO 扩展（LCD 复位 P1.0、PWR 键）|
| AXP2101 | 0x34 | PMIC / 电池 |
| QMI8658 | 0x6B | 6 轴 IMU |
| PCF85063 | 0x51 | RTC |
| ES8311 | 0x18 | 音频 codec |
| AXS15231B | 0x3B | 触摸 |

SD 卡（SDMMC 1-bit）：CLK=11 / CMD=10 / D0=9。摄像头 DVP：XCLK=38，Y9..Y2=21,39,40,42,46,48,47,45，VSYNC=17，HREF=18，PCLK=41。

## Arduino 初始化代码（官方）

```cpp
Arduino_DataBus *bus = new Arduino_ESP32QSPI(LCD_QSPI_CS, LCD_QSPI_CLK, LCD_QSPI_D0, LCD_QSPI_D1, LCD_QSPI_D2, LCD_QSPI_D3);
Arduino_GFX *g = new Arduino_AXS15231B(bus, -1, 0, false, 320, 480);
Arduino_Canvas *gfx = new Arduino_Canvas(320, 480, g, 0, 0, ROTATION);
```

## 与普通版（非 B）差异速查

| | ESP32-S3-Touch-LCD-3.5 | **3.5B（本文）** |
|---|---|---|
| 显示驱动 | ST7796（SPI）| AXS15231B（QSPI）|
| 刷新带宽 | 较低 | **更高（QSPI 4-bit）** |
| 引脚 | SPI 标准引脚 | QSPI D0-D3 |
| 其他 | — | 多麦克风/喇叭/摄像头接口 |

## 我的分析

- **8MB PSRAM 是数据可视化的关键**：LVGL 大 draw buffer（可到 1/4 屏）+ 图表数据缓存 + WiFi 缓冲都放得下，无需精打细算
- QSPI 比 SPI 快约 4 倍刷新，配合 LVGL 动画/图表更新更流畅；但**社区资料比普通版少**，搜教程要带 "3.5B" 或 "AXS15231B" 关键词
- 板载 IMU + RTC + 音频 = 做"环境数据采集+展示"一体机很省事（传感器数据 → 图表），无需外接模块

---

## 引用来源

- [Waveshare 官方文档平台](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B) | 官方文档
- [Waveshare Wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B) | 官方 Wiki
- [lvgl-micropython issue #530](https://github.com/lvgl-micropython/lvgl_micropython/issues/530) | QSPI 引脚参考
