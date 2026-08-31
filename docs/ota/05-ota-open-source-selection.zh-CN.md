> English version: [05-ota-open-source-selection.md](./05-ota-open-source-selection.md)

# 05-成熟开源 OTA 方案选型（优先采用，不造轮子）

> 日期: 2026-08-22
> 原则: 有好的开源方案/成熟方案就不自己造轮子（用户明确指示）
> 更新: 本文件取代 02 中的自研管道设想；04 的"自建 OTA 管道"建议被本文件的开源方案替代

---

## 零、架构边界（2026-08-24 更新，必须先读）

> ⚠️ 本文件选型的 **SafeGithubOTA / esp32FOTA 均为 Arduino 生态库**。本项目正式固件目标是 **ESP-IDF**（见项目操作契约与 `docs/hardware/board-spec-constraints.md`）。因此：
> - 本节结论是**开发期 Arduino 快速原型**的参考，**不得**作为 AW-006 生产 OTA 的落地实现。
> - AW-006 生产实现必须用 **ESP-IDF**（`esp_https_ota` / `advanced_https_ota`）+ GitHub Releases 分发 + `factory + ota_0 + ota_1` 双槽 + 显式失败回滚 + factory 恢复触发。
> - 触摸自检用 **AXS15231B（I2C 0x3B）**，不是 FT6336U。

---

## 一、结论先行

**推荐主方案: [SafeGithubOTA](https://github.com/gibz104/SafeGithubOTA)（MIT）——GitHub Releases 托管 + 自动回滚 + validation 回调 + 零自建服务器。**

**备选/增强: [esp32FOTA](https://github.com/chrisjoyce911/esp32FOTA)（LGPL）——需要固件 RSA 签名验证或自建服务器时。**

**官方兜底: esp_https_ota + advanced_https_ota 示例（需要完全自控/内网 OTA 时）。**

无需自研"下载→验签→esp_ota_write"管道——SafeGithubOTA 已封装完整流程（下载→flash→回滚），esp32FOTA 已实现签名验证。

---

## 二、两个核心候选深度对比

| 维度 | **SafeGithubOTA** ⭐ | **esp32FOTA** |
|---|---|---|
| 许可证 | MIT | LGPL |
| 托管 | **GitHub Releases**（免费，公网）| 自建 HTTP/HTTPS 服务器（manifest.json）|
| 固件来源验证 | HTTPS（GitHub TLS + 可选 PAT 私有仓库）| **RSA 4096 签名验证**（check_sig，最严）|
| 防变砖回滚 | ✅ **自动回滚**（bootloader 双分区 + validation 回调）| ⚠️ 无内置回滚（需自己配双分区 + rollback API）|
| 版本比较 | ✅ semver（MAJOR.MINOR.PATCH）| ✅ semver（semver.c）|
| 首次配置 | ✅ **Captive Portal**（WiFi AP + Web 表单，存 NVS）| ❌ 手动写死 manifest URL |
| 自动检查 | ✅ 定时器（如每 6h）| ✅ handle() 轮询 |
| 进度回调 | ✅ onProgress | ✅ setProgressCb（可接 TFT 进度条）|
| 校验回调 | ✅ onValidation（自检通过才确认固件）| ❌ 无（靠签名+重启）|
| 回滚检测 | ✅ wasRolledBack() | ❌ |
| 依赖 | **零外部依赖**（Arduino core 内置）| semver.c + 可选压缩库 |
| 文件系统更新 | ❌（仅固件）| ✅ spiffs/littlefs/fatfs 镜像 |
| 压缩固件 | ❌ | ✅ zlib/gzip（省流量）|
| 适合场景 | 开发期 + 小规模生产（有 GitHub 账号）| 自建服务器 + 需强签名 + 大固件省流量 |

## 三、选型逻辑（为什么 SafeGithubOTA 优先）

1. **免自建服务器**：GitHub Releases 即 OTA 服务器——发布固件 = 打个 tag + 上传 .bin，开发期最省事
2. **自动回滚开箱即用**：validation 回调（如"LVGL 渲染成功 + 触摸 I2C ACK + WiFi 连上"）返回 false → 自动回滚，正是我们 04 评估里要求的"自检超时/失败显式回滚"——库已封装
3. **Captive Portal 免手动配置**：设备首次开机 AP + 网页填仓库信息，比写死 URL 优雅（也符合我们 02 里"Wi-Fi provisioning 第二阶段"的设想）
4. **零依赖**：只用 WiFi/WiFiClientSecure/WebServer/Update/Preferences——PlatformIO/Arduino 直接编译
5. **GitHub 私有仓库 + PAT** 可选，公开仓库连 token 都不用（60 req/h 限速足够）

### esp32FOTA 的补位价值
- 需要**固件级签名验证**（防非法来源的最强手段，超过 HTTPS 传输保护）时，esp32FOTA 的 RSA 4096 签名是现成的——比自研"manifest 签名"简单得多
- 需要**内网/自建服务器**（设备不出网）时，manifest.json 模式更灵活
- 需要**压缩固件**（省 50-70% 流量）时

### 官方 esp_https_ota 的补位价值
- 需要完全自控升级时机/断点续传/预加密固件时，官方 advanced_https_ota 示例（版本检查 + anti-rollback + resumption）是生产级基线

---

## 四、推荐落地路径（修正 02 的方案）

```
Phase 1 开发期（免烧录快速迭代）:
  ArduinoOTA（IDE 直接无线烧录）→ 已经最快
  或直接上 SafeGithubOTA（GitHub Releases 即服务器，省得 IDE 也要连设备）

Phase 2 稳定期（推荐）:
  SafeGithubOTA
    - GitHub Releases 发版（tag = semver，附 .bin）
    - validation 回调 = 显示/触摸/WiFi/OTA 任务自检
    - 自动回滚 + wasRolledBack() 上报
    - 可选: PAT 私有仓库

Phase 3 生产增强（按需）:
  a) 需要固件签名 → esp32FOTA 的 RSA 签名（或官方 Secure Boot v2）
  b) 需要内网/自建服务器 → esp32FOTA manifest 模式 或 esp_https_ota
  c) 需要设备管理平台 → OTA Hub DIY / pleasedontcode 类平台（调研备选）
```

## 五、对本项目（AI Agent Status 显示终端）的具体适配

**validation 回调设计**（SafeGithubOTA onValidation）:
```cpp
ota.onValidation([]() -> bool {
    // 必过: 显示/触摸/WiFi/OTA 任务
    if (!display_init_ok()) return false;   // AXS15231B
    if (!touch_i2c_ok()) return false;      // AXS15231B（I2C 0x3B）
    if (WiFi.status() != WL_CONNECTED) return false;
    return true;  // WebSocket 服务器不可达不算失败（可降级）
});
```

**需要配置的分区表**（配合 rollback）:
- PlatformIO: `board_build.partitions = partitions_ota.csv`
- 双 ota 槽（ota_0/ota_1）+ otadata（SafeGithubOTA 的 rollback 依赖它）
- 参考 02 的 16MB 分区表（`nvs 0x8000 + otadata + factory + ota_0 + ota_1 + LittleFS`）。⚠️ **保留 factory 槽 + 显式恢复触发**（GPIO 长按或连续 N 次失败 `esp_ota_set_boot_partition(factory)`），不要去掉 factory 兜底路径（见 `docs/ota/04` 缺陷 2）

**已确认的坑**（README 明示）:
- `.ino` 里必须 `SET_LOOP_TASK_STACK_SIZE(16 * 1024)`（TLS 需要，默认 8KB 会崩）
- `begin()` 需在 WiFi 连上后调用（内部做 NTP 同步，TLS 证书校验需要准确时钟）
- PAT 明文存 NVS（私有仓库时注意）

---

## 引用来源

- [SafeGithubOTA (gibz104)](https://github.com/gibz104/SafeGithubOTA) | MIT | GitHub Releases OTA + rollback + captive portal
- [esp32FOTA (chrisjoyce911)](https://github.com/chrisjoyce911/esp32FOTA) | LGPL | manifest OTA + RSA 签名
- [ESP32 OTA 话题页 (GitHub topics)](https://github.com/topics/ota-firmware-updates) | esp_ghota / mcm-esp32-ota-fw-updater / OTA Hub DIY 等
- [ubirch-esp32-ota](https://github.com/ubirch/ubirch-esp32-ota) | IDF 组件，证书目录
- [ESP-IDF advanced_https_ota 示例](https://github.com/espressif/esp-idf/tree/master/examples/system/ota/advanced_https_ota) | 官方：版本检查 + anti-rollback + 续传
- [ESPHome OTA](https://esphome.io/components/ota/esphome/) | 生产级参考（password + safe mode）
- [Tasmota OTA](https://tasmota.github.io/docs/Upgrading/) | 生产级参考
- [SafeGithubOTA README 完整 API](https://github.com/gibz104/SafeGithubOTA#readme)
