> English version: [board-spec-constraints.md](./board-spec-constraints.md)

# Waveshare ESP32-S3-Touch-LCD-3.5B 板级规格与硬性约束

> 状态: authoritative（2026-08-24 依据官方 Wiki / docs 平台 / 产品页 / 官方 demo 仓库源码逐项核实）
> 本文件是开发与模拟的唯一硬件事实来源。与旧文档冲突时以本文件为准；真机测量（AW-002/003）发现差异时更新本文件并附证据。

## 1. 板卡标识

| 项目 | 值 |
|---|---|
| SKU | 31137（3.5B）；31334（3.5B-C，带外壳 + OV5640 摄像头）|
| SoC | ESP32-S3R8（Xtensa LX7 双核 240MHz）|
| RAM | 512KB SRAM + 384KB ROM + **8MB 堆叠 Octal PSRAM** |
| Flash | **16MB** W25Q128JVSIQ NOR Flash，**QIO** 模式 |
| 无线 | 2.4GHz Wi-Fi（802.11 b/g/n）+ Bluetooth 5 LE，板载天线（IPEX1 外接需改焊电阻）|

## 2. 显示（硬约束，勿错配）

| 项目 | 值 |
|---|---|
| 面板 | 3.5inch IPS 电容触摸，**320×480 竖屏（原生）**，262K 色 |
| 亮度 / 对比度 | 210 cd/㎡ / 1000:1 |
| 驱动 IC | **AXS15231B**（显示 QSPI + 触摸 I2C 一体）|
| 显示接口 | **QSPI（4-bit）**，SPI2_HOST，pclk **40MHz** |
| 像素格式 | RGB565（16bpp），RGB element order |
| 引脚 | CS=12，SCLK=5，D0=1，D1=2，D2=3，D3=4 |
| 背光 | GPIO6（LEDC 5kHz，10-bit PWM）|
| 复位 | **RST=NC**：由 TCA9554 扩展 IO（0x20）P1.0 输出复位脉冲（0→100ms→1）驱动；初始化显示前必须先做该脉冲 |

官方初始化（ESP-IDF BSP）要点：

```c
spi_bus_config_t buscfg = { .sclk_io_num = 5, .data0_io_num = 1,
                            .data1_io_num = 2, .data2_io_num = 3, .data3_io_num = 4,
                            .max_transfer_sz = max_transfer_sz };
spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO);
// io_config = AXS15231B_PANEL_IO_QSPI_CONFIG(12, NULL, NULL); io_config.pclk_hz = 40MHz
// panel: 16bpp, RGB order; vendor flags.use_qspi_interface = 1
```

Arduino 等价写法：`new Arduino_ESP32QSPI(12, 5, 1, 2, 3, 4)` + `new Arduino_AXS15231B(bus, -1, 0, false, 320, 480)`，`GFX_BL = 6`。

## 3. 触摸（硬约束，勿错配）

| 项目 | 值 |
|---|---|
| 控制器 | **AXS15231B 一体触摸**（不是 FT6336U / CST816 / GT911）|
| 接口 | I2C，地址 **0x3B**，400kHz |
| 触点 | 最多 2 点 |
| INT / RST | 均未接（GPIO_NUM_NC）|
| 读取协议 | 11 字节命令 `{0xb5,0xab,0xa5,0x5a,0x00,0x00,0x00,0x0e,0x00,0x00,0x00}`，读回 14 字节；坐标由 data[2..5]（及第二点 data[8..11]）解析，详见官方 `bsp_touch.c` |
| 坐标系 | 旋转 0 时直接映射 320×480，无 swap/mirror |

## 4. I2C 总线（单总线，SDA=8 / SCL=7，port 0，400kHz，内部上拉）

| 器件 | 7-bit 地址 | 用途 |
|---|---|---|
| TCA9554 | **0x20** | IO 扩展：LCD 复位（P1.0）、PWR 键检测（EXIO6）等 |
| AXP2101 | **0x34** | PMIC：电池充放电、多路电源、电量/电压 ADC |
| QMI8658 | **0x6B** | 6 轴 IMU（加速度 + 陀螺仪）|
| PCF85063 | **0x51** | RTC（AXP2101 供电，断电不掉时间）|
| ES8311 | **0x18** | 音频 codec（板载麦克风 + MX1.25 喇叭，I2S 数据）|
| AXS15231B | **0x3B** | 触摸 |

摄像头 SCCB 复用同一总线（SIOD=8 / SIOC=7）。

> ⚠️ 同一 I2C 总线上有 6 个器件 + 摄像头，多任务访问必须用互斥锁（官方 BSP 用递归互斥量 bsp_i2c_mux）。

## 5. 其他外设引脚

| 外设 | 引脚 |
|---|---|
| SD 卡（SDMMC，**1-bit**）| CLK=11，CMD=10，D0=9 |
| 摄像头 DVP | XCLK=38，Y9=21，Y8=39，Y7=40，Y6=42，Y5=46，Y4=48，Y3=47，Y2=45，VSYNC=17，HREF=18，PCLK=41，PWDN/RESET=-1 |
| BOOT 键 | GPIO0（低电平按下；按住上电进下载模式）|
| PWR 键 | 经 TCA9554（单击开机；正常态可编程；长按 6s 关机）|
| RESET 键 | 硬件复位 |
| 电池 | MX1.25 2P 3.7V 锂电（AXP2101 充放电）|
| RTC 后备 | SH1.0 |

## 6. 工具链与构建配置约束

- **ESP-IDF**：官方 demo 要求 ≥5.1，Wiki 教程按 ≥5.4 编写 → 本项目固定 **≥5.4**（AW-002 记录精确版本）。
- **Arduino**：esp32 core ≥3.2.0；**分区方案必须选 "16M Flash(3MB APP/9.9MB FATFS)"** 或自定义 16MB 分区表；串口打印需开 **USB CDC On Boot**（Type-C 为 ESP32-S3 原生 USB，不是外部 UART 桥）。
- 关键 sdkconfig（官方 demo 值，勿随意改）：

```ini
CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y
CONFIG_ESPTOOLPY_FLASHMODE_QIO=y
CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_OCT=y      ; 8MB Octal PSRAM
CONFIG_SPIRAM_SPEED_80M=y
CONFIG_LV_COLOR_16_SWAP=y     ; RGB565 字节交换（LVGL **v8.4** flush 必需；v9.x 无此宏，改由 display driver 的 color format 处理，AW-005 按所选版本确认）
```

- 官方组件依赖（`idf_component.yml`）：`espressif/esp_lcd_axs15231b ^1.0.0`、`espressif/esp_io_expander_tca9554 ^2.0.0`、`espressif/esp_codec_dev ^1.3.4`、`espressif/button ^4.1.0`、`lvgl/lvgl ~8.4.0`。
- LVGL 版本：官方 Arduino demo 支持 **v8.4.0 或 v9.2.2**；本仓库 PC simulator 为 **LVGL 9.6**。生产固件版本须在 AW-005 锁定并写入 UI 文档（对齐 sim 选 v9.x，或对齐官方 demo 选 v8.4，二选一，禁止混用 API）。
- LVGL 内存基线（官方 factory）：LV_MEM_SIZE 48KB；显示缓冲 **全屏 PSRAM buffer（320×480×2 = 300KB，buff_spiram=true）** + LVGL flush trans_size = 1/10 屏；LVGL 任务 core 1，优先级 4，栈 5KB，timer 5ms。
- 下载方式：Type-C 原生 USB + 板载自动下载电路（无需手动 BOOT）；程序崩溃时按住 BOOT 再上电强制进下载模式。

## 7. 分区表约束（对 OTA 任务 AW-006 关键）

- 官方 demo 分区表**只有 factory（6M，偏移 0x10000）+ nvs（0x6000）+ phy_init**，**没有 OTA 双槽**。
- 本项目 OTA 目标需要 **factory + ota_0 + ota_1（双 OTA app 分区 + otadata）** 的自定义分区表；分区表必须在 AW-002 真机验证前冻结并写入 `firmware/`。
- 参考 docs/ota/04 结论：nvs 建议扩到 0x8000（OTA 续传 + Wi-Fi 状态），storage 用 LittleFS。

## 8. 模拟器对应规则（PC sim 不得违背）

1. 分辨率 **320×480 竖屏**、**RGB565 16bpp** —— sim 必须与此一致（当前 `sim/lvgl-sim` 已满足）。
2. 触摸：电容 2 点 → sim 至少支持单点拖拽；坐标**不旋转**（ROT 0），sim 触摸方向必须与设备一致。
3. **性能结论只能在真机下**：帧率、触摸延迟、内存/PSRAM、Wi-Fi 重连、OTA 回滚。sim 只验证布局、滑动规则、状态映射、交互语义。
4. 不要因为 sim 流畅就假设 QSPI 40MHz 刷新带宽、PSRAM 大小或 DMA 行为；不要用 sim 结论替换真机验收。
5. 中文字体：设备端必须内置字体（LVGL 字体转换），sim 的 PC 字体仅作布局参考。

## 9. 常见错误对照（防止错配的检查清单）

| 错误做法 | 正确做法 |
|---|---|
| 用 ST7796 / Arduino_TFT / SPI 单线驱动 | AXS15231B **QSPI**（4-bit）|
| 用 FT6336U / CST816 / GT911 触摸驱动 | AXS15231B 触摸，I2C **0x3B** |
| 按 480×320 横屏设计 UI | 320×480 竖屏原生，ROT 0 |
| 用 8MB 或默认分区表 / 4MB 分区 | 16MB QIO + 自定义分区表 |
| 把 LCD RST 接到某个 GPIO | RST=NC，用 TCA9554 P1.0 复位脉冲 |
| 用 SPI1/SPI3 或 FSPI 默认引脚 | SPI2_HOST + 上述固定引脚 |
| 跳过 TCA9554 复位脉冲直接 init 显示 | 必须先脉冲（0→100ms→1）|
| 把非 B 版（ESP32-S3-Touch-LCD-3.5）引脚/驱动搬过来 | 一律以本文件为准 |

## 10. 引用来源（2026-08-24 核实）

- Wiki: https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B
- Docs 平台: https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B
- 产品页: https://www.waveshare.com/product/esp32-s3-touch-lcd-3.5b.htm
- 官方 demo 仓库: https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.5B
  - `Arduino/examples/08_gfx_helloworld`、`09_lvgl_arduino_v8`（QSPI 引脚、BL=6、TCA9554）
  - `ESP-IDF/01_factory/components/esp_bsp/`（bsp_display/bsp_touch/bsp_i2c/bsp_sdcard/bsp_camera/bsp_axp2101 等）
  - `ESP-IDF/01_factory/sdkconfig.defaults`、`partitions.csv`、`main/idf_component.yml`
- 数据手册（Wiki Resources → Datasheets）：AXS15231B、ESP32-S3 Series Datasheet 等
