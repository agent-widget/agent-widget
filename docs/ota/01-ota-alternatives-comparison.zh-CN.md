> English version: [01-ota-alternatives-comparison.md](./01-ota-alternatives-comparison.md)

# 01-ESP32-S3 OTA 方案调研与对比

> 日期: 2026-08-22
> 硬件: Waveshare ESP32-S3-Touch-LCD-3.5B（ESP32-S3R8，8MB PSRAM / 16MB Flash）
> 目的: 设计 OTA 方案——后续开发免烧录 + 容错防变砖 + 固件验证防非法来源/不完整
> 状态: 调研完成，方案对比，待选型细化

---

## 一、需求梳理

| 需求 | 说明 |
|---|---|
| 免频繁烧录 | 开发/部署阶段经 WiFi 更新固件，无需 USB 线 |
| 容错防变砖 | 新固件失败自动回滚到上一可用版本 |
| 固件验证 | 拒绝非法来源（签名验证）和不完整固件（完整性校验） |
| 易用性 | 开发期简单，生产期可靠，两者兼顾 |

## 二、候选方案全景

### 方案 A: ArduinoOTA / ElegantOTA（开发期）
- **原理**: Arduino 库，IDE 或 Web 页面直接上传固件到设备
- **优点**: 极简单，开发期 5 分钟上手
- **缺点**: ❌ 无签名验证（任何人可上传）、❌ 无自动回滚（依赖分区表）、❌ 依赖 Arduino 生态

### 方案 B: ESP-IDF 原生 OTA（双分区 + rollback）⭐
- **原理**: 官方 app_update 组件，ota_0/ota_1 双分区 + otadata 分区 + `esp_ota_mark_app_valid_cancel_rollback()`
- **流程**: 下载新固件到空闲分区 → 校验通过 → 切 boot 分区 → 重启 → 新固件自检 → 成功则标记 valid，失败则自动回滚
- **优点**: ✅ 官方维护、✅ 自动回滚防变砖、✅ 支持 Secure Boot v2 签名验证、✅ 灵活（HTTP/HTTPS 均可）
- **缺点**: ESP-IDF 上手曲线陡；Arduino 框架下需额外配置

### 方案 C: esp_https_ota（HTTPS 简化版）⭐
- **原理**: app_update 之上的 HTTPS 抽象层，`esp_https_ota()` 一行完成下载+写入+切分区
- **优点**: ✅ 官方组件、✅ 内置 TLS 服务器验证（cert_pem）、✅ 支持 OTA 续传（resumption）、✅ 支持部分下载（省 RAM）、✅ 事件系统监控进度
- **缺点**: 需要 HTTPS 服务器（本地开发可用 mTLS 或自签证书）；Arduino 框架下可用 `Update` 类或 IDF 组件

### 方案 D: Secure Boot v2 + Flash Encryption（生产级安全）⭐
- **原理**: 出厂烧录 eFuse → bootloader 验证签名 → 固件加密存储
- **优点**: ✅ 最强防非法来源（硬件级签名验证）、✅ 防固件提取
- **缺点**: ❌ **烧录 eFuse 不可逆**（一次性决定）、❌ 需要密钥管理、❌ 开发调试受限（需签名的固件才能跑）

### 方案 E: 自定义服务器 + 版本检查 + 清单文件（应用层）
- **原理**: 设备轮询 HTTP 服务器 → 下载 manifest.json（版本/hash/URL）→ 校验 hash → 下载固件
- **优点**: 完全可控、无框架依赖
- **缺点**: 重复造轮子；无官方 rollback 状态机支持（需自己实现）

### 方案 F: 差分升级（Delta OTA）
- **原理**: 只下载新旧固件差异部分（Xdelta 等）
- **优点**: ✅ 省带宽（大固件时明显）
- **缺点**: 需要服务端 diff 计算 + 客户端合并，复杂度高，**16MB Flash 场景收益有限**

## 三、横向对比

| 维度 | A: ArduinoOTA | B: IDF 原生 | C: esp_https_ota | D: Secure Boot | E: 自建清单 | F: 差分 |
|---|---|---|---|---|---|---|
| 防变砖回滚 | ❌ 无 | ✅ 自动 | ✅ 自动 | ✅ 自动 | ⚠️ 自实现 | ✅ 依赖 B/C |
| 防非法来源 | ❌ | ✅ (SBv2) | ✅ (HTTPS) | ✅✅ (硬件) | ⚠️ hash | ✅ (SBv2) |
| 防不完整固件 | ⚠️ 部分 | ✅ 校验 | ✅ 校验+续传 | ✅ | ✅ hash | ✅ |
| 开发易用性 | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐ |
| 生产可靠性 | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| 官方支持 | Arduino 库 | ✅ | ✅ | ✅ | ❌ | 社区 |
| 适合阶段 | 开发期 | 全部 | 全部 | 生产期 | 定制 | 大固件 |

## 四、选型建议（我的分析）

**推荐组合：方案 B（IDF 原生 OTA 双分区 + rollback）为主干，方案 C（esp_https_ota）为传输层，方案 D（Secure Boot v2）为生产期增强。**

理由：
1. **开发期**（免烧录）：先 ArduinoOTA 快速迭代 → 固件稳定后切 esp_https_ota
2. **生产期**（可靠）：IDF 原生 OTA 的 rollback 状态机是官方验证过的防变砖核心；esp_https_ota 提供 HTTPS 传输安全 + 续传能力
3. **安全增强**：Secure Boot v2 签名验证彻底杜绝非法固件——但**必须在首次烧录时决定**（eFuse 一次性），开发期可先不开，发布前开启

### 为什么不用差分升级
16MB Flash 分区给 ota_0/ota_1 各 4MB 绰绰有余，固件通常 <2MB，差分收益（省几 MB 传输）不值得引入服务端 diff 复杂度。

---

## 引用来源

- [ESP-IDF OTA 官方文档 (ESP32-S3)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html)
- [ESP HTTPS OTA 官方文档](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/esp_https_ota.html)
- [Maker Gear Lab: Firmware Rollback Mechanism](https://makergearlab.com/developing-a-firmware-rollback-mechanism-for-esp32-devices-after-failed-ota-updates/)
- [IOT Journal: Prevent Bricking Field Devices](https://www.iotjournal.ir/esp32-ota-update-guide-how-to-prevent-bricking-field-devices/)
- [SunFounder: ArduinoOTA & ElegantOTA 指南](https://www.sunfounder.com/blogs/news/esp32-ota-updates-a-complete-guide-to-arduinoota-and-elegantota-firmware-upgrades)
- [知乎: ESP32 HTTPS OTA 升级](https://zhuanlan.zhihu.com/p/721592546)
- [掘金: 从ESP32双分区到差分升级的工程化实践](https://juejin.cn/post/7671153017659654207)
