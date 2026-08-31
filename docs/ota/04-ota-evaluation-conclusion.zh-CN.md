> English version: [04-ota-evaluation-conclusion.md](./04-ota-evaluation-conclusion.md)

# 04-OTA 设计方案评估结论（整理版）

> 日期: 2026-08-22
> 评估模型: deepseek-v4-pro（推理模型，57K 字符评估原文见 03 文档）
> 评估对象: 02-ota-design-esp-https-rollback.md
> 本文: 从 03 原始推理流提炼的结构化结论
> ⚠️ 更新 (2026-08-22): 评估针对 02 自研设计。用户指示"有成熟方案不造轮子"后，落地改为开源方案（见 05-ota-open-source-selection.md）。本文件的**缺陷洞察仍有价值**——选型时用它校验开源方案是否覆盖这些点（如 SafeGithubOTA 已覆盖缺陷 1 的完整性校验 + 缺陷 3 的回滚时序，缺陷 2 的 factory 兜底仍建议保留）。

---

## 一、总体结论

**方案可行但有条件，v0.1 不可直接用于生产。** 架构方向正确（esp_https_ota + 双分区 rollback + Secure Boot v2 分层），但存在 3 个必须修复的严重缺陷和若干补充项。

---

## 二、严重缺陷（按严重程度排序）

### 缺陷 1: manifest 的 sha256 未被实际校验（完整性缺口）

- **问题**: 设计流程"拉取 manifest → 版本检查 → esp_https_ota 下载"中，`manifest.json` 里的 `sha256` 字段**只是摆设**——代码示例直接下载 `latest.bin`，没有校验 manifest 签名和固件哈希
- **风险**: 依赖 HTTPS 传输安全 ≠ 固件完整。服务器被入侵/CI 误发布/下载截断时，坏固件直接写入 OTA 槽
- **修复**: 应用层自建 OTA 管道: HTTP 下载 → 临时区（PSRAM/SPIFFS）→ 校验 manifest 签名（RSA/ECDSA，公钥内置）+ SHA256 → 通过才 `esp_ota_write` 到目标分区。或下载后重启前读回校验

### 缺陷 2: factory 兜底分区没有触发路径

- **问题**: 分区表设计了 factory 槽，但**没有任何代码路径能跳回 factory**。若 ota_0/ota_1 都坏了，bootloader 只在 otadata 无效时自动选 factory——但正常流程不会主动触发
- **修复**: 增加恢复机制:
  - 方案 a: GPIO 长按（如 BOOT 键 5s）→ 应用层调 `esp_ota_set_boot_partition(factory_partition)` → 重启
  - 方案 b: 连续 N 次启动失败 → NVS 计数 → 自动跳 factory
  - factory 固件做成"最小 OTA 恢复固件"（仅 WiFi + OTA 功能），这是生产级标准策略

### 缺陷 3: rollback 时序认知偏差（防变砖核心）

- **问题**: 设计写"自检失败/超时 → 硬件 watchdog 复位 → bootloader 自动回滚"，但**IDF 的自动回滚不是这样工作的**:
  - 自动回滚仅当: 新固件**崩溃/WDT 复位后**，bootloader 检测到状态仍为 `PENDING_VERIFY` 才触发
  - 若代码在自检前误调用了 `esp_ota_mark_app_valid_cancel_rollback()`，之后崩溃**不会回滚**
  - 若新固件卡死且未产生复位（无 WDT），也不会回滚
- **修复**:
  - 显式设置自检超时定时器（如 30-60s），超时/失败路径必须调用 `esp_ota_mark_app_invalid_rollback_and_reboot()`
  - 自检**全部通过后才**调用 mark_valid，绝不能提前
  - 启用 `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` + task WDT

---

## 三、五个待评估问题的回答

### Q1: ArduinoOTA（Phase1）与 esp_https_ota（Phase2）分区表切换边界？

**回答**: 边界在**板级分区表配置**，不在代码。
- ArduinoOTA 用 Arduino `Update` 类，需 PlatformIO 配置 `board_build.partitions = custom_partitions.csv`
- 从 Phase 1 到 Phase 2 不需要换分区表——**一开始就用最终分区表**（含 factory/ota_0/ota_1），ArduinoOTA 写 ota 槽、esp_https_ota 也写 ota 槽，两者兼容
- 关键: 开发期 ArduinoOTA 上传的是未签名固件 → Secure Boot v2 必须**最后**才启用

### Q2: Secure Boot v2 对开发调试的影响？

**回答**:
- 启用后: 所有烧录的 app（含 factory/ota_0/ota_1）必须签名，否则拒绝启动
- JTAG 调试仍可用（Secure Boot 不锁 JTAG，Flash Encryption 才锁）
- 串口日志不受影响
- 影响最小化的策略: 开发期完全不启用；发布前一次性烧 eFuse + 所有槽刷签名固件。**eFuse 不可逆，务必先备份密钥**

### Q3: 8MB PSRAM 下 partial_http_download 是否值得？

**回答**: **不值得作为默认**。默认 mbedTLS Rx buffer 16KB 已够，partial 模式只省 ~12KB RAM——对 8MB PSRAM 无意义，且增加代码复杂度（分块请求）。
- 保持默认（单请求流式下载）即可
- 8MB PSRAM 的真正价值: 下载缓冲区可以开大（如 32-64KB），提高吞吐

### Q4: 显示终端（无传感器）什么算"自检通过"？

**回答**（本地关键路径为准）:
- **必过**: RTOS 启动、LVGL 初始化并渲染本地测试页、背光、触摸 I2C ACK、WiFi STA 连接并获取 IP、OTA 任务存活
- **可降级**: WebSocket 服务器连接/收到消息——**服务器不可达不应回滚**（否则云端故障会把好固件标记为坏）
- 流程: 启动后 30-60s 稳定无复位；硬件/初始化失败 → mark_invalid_rollback；远程服务失败只记录不 fail
- 建议: 设计一个 "minimum local UI" 显示设备状态，渲染成功即证明显示/触摸可用

### Q5: manifest 签名能否作为 Secure Boot 前的过渡？

**回答**: **可以，但有条件**。至少做到:
- manifest 签名（RSA/ECDSA，公钥内置）
- 固件 sha256 在写入 OTA 分区**前**校验
- 版本单调递增/禁止回退（min_version）
- 防重放: manifest 带 issued_at/nonce，新鲜性校验
- HTTPS pinned CA

⚠️ 注意: 应用层校验不能防 UART/JTAG 刷入自定义固件（只保护 OTA 通道）；且 esp_https_ota 边下边写时 sha256 校验别扭——建议自定义管道: 下载到临时区 → 验签+SHA256 → esp_ota_write。

---

## 四、补充遗漏的关键点

1. **分区表修正**（建议）: nvs 扩到 0x8000（OTA resumption + WiFi 状态存储更宽裕）、storage 用 **LittleFS**（SPIFFS 在 IDF 已边缘化）、分区表偏移保持 0x8000
2. **功耗/掉电**: OTA 下载是功耗高峰（WiFi + flash 写）；下载期间 `esp_wifi_set_ps(WIFI_PS_NONE)` 防断连，写 flash 前确认供电稳定（brownout detector）；若电池供电，电量不足时禁止 OTA
3. **Flash 磨损**: ota_resumption 不要每 chunk 写 NVS，周期性保存 offset 或仅中断时保存
4. **证书轮换**: cert_pem 应内置根 CA（非叶证书）；预留轮换机制（manifest 下发新公钥需 manifest 签名，或烧录两个根证书）
5. **资产版本化**: storage 分区资源（字体/图片）与固件版本可能不兼容——资产需带版本号，回滚时避免新旧固件共用不兼容资源
6. **诊断**: NVS 保存 boot count / crash reason / OTA 状态，用于回滚原因分析（遥测）
7. **anti-rollback 风险**: Secure Boot v2 的 security version 设置错误会变砖——min_version 必须与 security version 对齐

---

## 五、修订后的推荐流程（v0.2 方向）

```
检查更新
  → HTTPS 拉取 manifest（签名验证 + fresh 检查）
  → 版本 > 当前？
  → 下载固件到临时区（PSRAM/SPIFFS）
  → 校验 sha256 + 签名
  → esp_ota_write 到空闲槽
  → 重启（bootloader 置 PENDING_VERIFY）
  → 自检（30-60s: 显示/触摸/WiFi/OTA 任务）
  → 全过 → mark_valid | 失败/超时 → mark_invalid_rollback
  → 连续失败 N 次 / GPIO 长按 → 跳 factory 恢复固件
```

---

## 引用来源

- [03-ota-design-evaluation.md](./03-ota-design-evaluation.md) | deepseek-v4-pro 原始评估（57K 字符）
- [02-ota-design-esp-https-rollback.md](./02-ota-design-esp-https-rollback.md) | 被评估的设计稿
- [ESP-IDF OTA 官方](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html)
