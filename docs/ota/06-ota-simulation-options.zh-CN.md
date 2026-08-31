> English version: [06-ota-simulation-options.md](./06-ota-simulation-options.md)

# 06-ESP32 整机模拟方案调研（能否在 PC 上跑通 OTA 全流程）

> 日期: 2026-08-22
> 问题: 除了 LVGL 界面模拟器（已建 esp32-lvgl-sim），是否有整套模拟能跑通 OTA（下载→写 flash→重启→验证→回滚）？
> 结论: ✅ **有，三条路**（Wokwi / QEMU / ESP-IDF Linux target），各有取舍

---

## 一、结论速览

| 方案 | 运行方式 | WiFi 模拟 | OTA 可跑通? | 界面 | 适合 |
|---|---|---|---|---|---|
| **Wokwi** ⭐ | 浏览器 | ✅ 完整虚拟 AP（Wokwi-GUEST）+ 真实网络栈 + PCAP 抓包 | ✅ 有现成 OTA 示例项目 | ✅ 虚拟 LCD 可显示 | Arduino 生态最快验证 |
| **QEMU（espressif fork）** ⭐ | 本机 | ✅ WiFi NIC 模拟（esp32_wifi）+ qemu_internet 组件 | ✅ flash 持久化 + bootloader 真实执行 | ✅ 虚拟 framebuffer（esp_lcd_qemu_rgb） | ESP-IDF 工程 + 严谨回滚/Secure Boot 测试 |
| **ESP-IDF Linux target** | 本机编译 | ⚠️ 组件级（esp_wifi host 实现，有限） | ⚠️ 部分组件支持，OTA 未完整 | ❌ | 单元测试/CI |
| **Velxio**（官方新） | 浏览器 | ✅ | 待验证 | ✅ | 新选择，观望 |

## 二、方案详情

### 2.1 Wokwi（最省事，推荐先用它验证 OTA 逻辑）

- **地址**: https://wokwi.com —— 浏览器即用，无安装
- **WiFi 模拟**: 虚拟 AP `Wokwi-GUEST`（无密码，channel 6），完整 802.11 → IP → TCP/UDP → DNS/HTTP/MQTT 网络栈，**可下载 PCAP 用 Wireshark 分析流量**
- **OTA 支持**: 官方示例 [OTA](https://wokwi.com/projects/389801812438455297) + [WiFi ota test](https://wokwi.com/projects/387266104488294401) —— flash 可写入 + 重启后保留，能验证"下载→写 flash→重启→新固件运行"
- **Arduino 兼容**: 直接跑 Arduino core 编译的固件（我们的 PlatformIO/Arduino 工程可移植）
- **限制**: 免费版 Public Gateway 走云（流量被监控）；私有网关（连本机 localhost）需付费；没有真实外设时序（I2C/SPI 触摸模拟有限）

### 2.2 QEMU（espressif fork，最严谨，适合回滚/Secure Boot 验证）

- **安装**: `python $IDF_PATH/tools/idf_tools.py install qemu-xtensa` + 系统依赖（libgcrypt20/libglib2.0-0/libpixman-1-0/libslirp0）
- **启动**: `idf.py qemu monitor`（编译+模拟+串口监视）| `idf.py qemu --gdb monitor`（GDB 调试）
- **模拟能力**:
  - CPU/内存/外设 + **flash 持久化**（qemu_flash.bin：bootloader + 分区表 + app 按偏移放置）
  - **eFuse 模拟**（`idf.py qemu efuse-burn ...`）→ **Secure Boot / Flash Encryption 可无风险测试**（真机烧 eFuse 不可逆，QEMU 随便试）
  - **WiFi/BLE NIC 模拟**（esp32_wifi）+ 网络访问（qemu_internet 组件做 HTTP 下载）
  - **虚拟 framebuffer**（`--graphics` + esp_lcd_qemu_rgb 组件）→ LVGL UI 可显示
- **OTA 验证意义**: 双分区切换、bootloader 回滚逻辑、PENDING_VERIFY 状态机、Secure Boot 签名验证——**全部真实执行**，与真机行为一致
- **限制**: 面向 ESP-IDF 工程（我们的 Arduino 工程需移植或走 idf.py 构建）；无真实触摸/外设时序

### 2.3 ESP-IDF Linux target（host 编译）

- 文档: "Running ESP-IDF Applications on Host"
- 组件在 Linux 上实现（esp_wifi 有 host 模拟），可做 CI 单元测试
- **目前只有有限组件支持，OTA 链路未完整** —— 不适合跑通全流程

### 2.4 Velxio（Espressif 2026-07 新发布）

- 浏览器 QEMU 内核模拟，跑真固件 + WiFi/MQTT demo
- 新项目，成熟度待观察，暂列备选

## 三、对我们的推荐路径（结合现有环境）

```
开发阶段 1（UI 迭代）:  LVGL PC 模拟器（已建 esp32-lvgl-sim）✅
开发阶段 2（OTA 逻辑）: Wokwi（Arduino 工程 + 现成 OTA 示例，最快跑通"下载→重启→新版")
开发阶段 3（严谨验证）: QEMU + ESP-IDF（双分区回滚 / Secure Boot / eFuse 模拟）
                       —— 与 05 选型的 esp_https_ota 路径完全对应
真机阶段:              ESP32-S3-Touch-LCD-3.5B（最终验收）
```

## 四、关键提醒

1. **Wokwi 验证的是"应用逻辑"**（HTTP 下载 + Update 类写 flash + 重启），bootloader 回滚状态机依赖 Arduino core 的 rollback 支持——需确认 Wokwi 的 ESP32-S3 模型分区表是否含 otadata
2. **QEMU 验证的是"系统行为"**（bootloader + otadata + 回滚），是模拟 OTA 最接近真机的方式；eFuse 模拟让 Secure Boot 测试零风险
3. 两者互补：**Wokwi 快、QEMU 准**
4. OTA 服务器：本机起 HTTPS 静态服务即可（开发期），Wokwi 用 Public Gateway 访问公网 GitHub Releases（对应 SafeGithubOTA 方案）或私有网关访问本机

---

## 引用来源

- [ESP-IDF QEMU Emulator (ESP32-S3) 官方文档](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/tools/qemu.html)
- [Wokwi ESP32 WiFi 模拟文档](https://docs.wokwi.com/guides/esp32-wifi)
- [Wokwi OTA 示例项目](https://wokwi.com/projects/389801812438455297)
- [Wokwi WiFi OTA test](https://wokwi.com/projects/387266104488294401)
- [Ebiroll/qemu_esp32（WiFi NIC 模拟）](https://github.com/Ebiroll/qemu_esp32)
- [Production ESP32: Internet Access in QEMU](https://productionesp32.com/posts/internet-in-qemu/)
- [ESP-IDF Running Apps on Host](https://esp32.ai/idf/esp32/api-guides/host-apps)
- [Velxio: Browser-based ESP32 simulation (官方博客)](https://developer.espressif.com/blog/2026/07/velxio-browser-based-esp32-simulation/)
