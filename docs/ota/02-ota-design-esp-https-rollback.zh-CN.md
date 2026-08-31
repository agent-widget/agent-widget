> English version: [02-ota-design-esp-https-rollback.md](./02-ota-design-esp-https-rollback.md)

# 02-OTA 细化设计：esp_https_ota + 双分区 Rollback + Secure Boot v2

> 日期: 2026-08-22
> 基于: 01-ota-alternatives-comparison.md（选型结论）
> 硬件: ESP32-S3-Touch-LCD-3.5B（16MB Flash / 8MB PSRAM）
> 状态: 设计稿（v0.1）
> ⚠️ 更新 (2026-08-22): **本稿的自研管道设计已被 05-ota-open-source-selection.md 的开源方案替代**（SafeGithubOTA / esp32FOTA）。保留本稿作原理参考（分区表/状态机/自检设计仍有价值），落地以 05 为准。

---

## 一、目标架构

```
┌────────────┐   HTTPS    ┌──────────────────┐
│ OTA Server │◀──────────▶│  ESP32-S3 设备    │
│ (静态文件)  │  拉取固件   │  ┌─────────────┐ │
│  firmware/ │            │  │ App (LVGL)  │ │
│  latest.bin│            │  └──────┬──────┘ │
│  manifest. │            │  esp_https_ota   │
│  json      │            │  └──────┬──────┘ │
└────────────┘            │  ota_0 / ota_1   │
                          │  (双分区 + 回滚)  │
                          └──────────────────┘
```

**核心组成**:
1. **分区表**: ota_0 + ota_1 双应用分区 + otadata + NVS（存储 OTA 状态）
2. **传输**: HTTPS（esp_https_ota，校验服务器证书）
3. **验证**: 固件签名（Secure Boot v2，可选生产增强）+ 固件头校验（app_desc 版本号）
4. **回滚**: IDF 原生 rollback 状态机（PENDING_VERIFY → VALID / INVALID）

---

## 二、分区表设计（16MB Flash）

```
# Name,   Type, SubType, Offset,  Size,   Flags
nvs,      data, nvs,     0x9000,  0x6000,
otadata,  data, ota,     0xf000,  0x2000,
phy_init, data, phy,     0x11000, 0x1000,
factory,  app,  factory, 0x20000, 0x400000,   # 出厂固件（4MB）
ota_0,    app,  ota_0,   0x420000, 0x400000,  # OTA 槽 A（4MB）
ota_1,    app,  ota_1,   0x820000, 0x400000,  # OTA 槽 B（4MB）
storage,  data, spiffs,  0xc20000, 0x3E0000,  # 资源/字体/配置
```

**关键点**:
- 16MB Flash 充裕：3 个 4MB 应用槽 + 4MB 存储（SPIFFS 用于 LVGL 字体/图片资源）
- 保留 factory 槽做最后兜底（可跳回出厂固件）
- otadata 记录 `ota_seq` 计数器 + 状态（IDLE/PENDING_VERIFY/VALID/INVALID）

## 三、固件更新流程（状态机）

```
[启动] → 检查 otadata
  ├─ PENDING_VERIFY → 自检（见下）
  │    ├─ 自检通过 → esp_ota_mark_app_valid_cancel_rollback() → VALID
  │    └─ 自检失败/超时 → esp_ota_mark_app_invalid_rollback_and_reboot() → 回滚
  └─ VALID → 正常运行 → 定时检查更新

[检查更新] → 拉取 manifest.json
  ├─ 版本号 ≤ 当前 → 跳过
  └─ 版本号 > 当前 → esp_https_ota 下载到空闲分区
       ├─ 下载完成 → 校验（签名/哈希）→ esp_restart()
       └─ 失败 → 保留旧固件，下次重试
```

### 自检（PENDING_VERIFY 阶段，关键防变砖）

新固件首次启动进入 PENDING_VERIFY 状态，需在超时窗口内完成：

| 检查项 | 方法 |
|---|---|
| 基础启动 | 启动 30 秒内未崩溃（task watchdog 兜底）|
| 显示初始化 | LVGL + AXS15231B 初始化成功 |
| 触摸初始化 | AXS15231B（I2C 0x3B）通信正常 |
| WiFi 连接 | 指定时间内连上 AP |
| 关键服务 | OTA 检查线程存活 |
| 版本自报 | app_desc.version 与 manifest 一致 |

全部通过 → `esp_ota_mark_app_valid_cancel_rollback()`；任一失败或超时 → **显式调用 `esp_ota_mark_app_invalid_rollback_and_reboot()` 回滚到上一槽**。⚠️ 不能只靠硬件 watchdog 复位触发回滚（IDF 自动回滚仅在崩溃/WDT 复位且状态仍为 PENDING_VERIFY 时发生；若提前误调 mark_valid 或卡死无复位都不会回滚）。自检必须全部通过后才 mark_valid。

## 四、传输与验证细节

### 4.1 HTTPS 传输（esp_https_ota）

```c
esp_http_client_config_t http_config = {
    .url = "https://ota.example.com/firmware/latest.bin",
    .cert_pem = (char *)server_root_cert_pem,   // 服务器根证书（内置）
    .timeout_ms = 30000,
};
esp_https_ota_config_t ota_config = {
    .http_config = &http_config,
    .ota_resumption = true,    // 支持断点续传
};
esp_err_t ret = esp_https_ota(&ota_config);
if (ret == ESP_OK) esp_restart();
```

**特性利用**:
- `cert_pem`: 只信任我们自己的服务器（自签根证书烧录进固件），杜绝中间人/非法源
- `ota_resumption`: 下载中断后从上次位置续传（存 NVS），避免反复全量下载
- `partial_http_download`: 大固件分块下载，省 RAM（8MB PSRAM 下非必需但可选）
- 事件系统: 监听 `ESP_HTTPS_OTA_*` 事件驱动 UI 进度条（LVGL 显示升级进度）

### 4.2 固件验证（双重）

| 层 | 机制 | 防什么 |
|---|---|---|
| **传输层** | HTTPS + 服务器证书校验 | 中间人/伪装服务器 |
| **签名层**（Secure Boot v2）| 固件 RSA/ECDSA 签名 | 非法固件（非官方构建）|
| **完整性** | esp_ota 内置镜像校验（header + hash）| 下载损坏/截断 |

### 4.3 Secure Boot v2（生产期启用）

- 首次烧录时 `idf.py efuse burn-key` 烧入签名公钥 → 之后 bootloader 只运行签名匹配的固件
- **⚠️ eFuse 一次性**: 启用前必须确认——开发期可先用软校验（应用层验证 manifest 签名），生产发布前再硬件启用
- 签名流程: `idf.py signed-app` → 生成 `.signed.bin` → 上传服务器

## 五、OTA 服务器设计（开发期最小可用）

```bash
# 简单静态服务器（nginx 或 python http.server + HTTPS）
/var/www/ota/
├── manifest.json          # {version, url, sha256, size}
└── firmware/
    └── v1.2.0.bin         # 构建产物
```

**manifest.json 结构**:
```json
{
  "version": "1.2.0",
  "url": "https://ota.example.com/firmware/v1.2.0.bin",
  "sha256": "a1b2c3...",
  "size": 1048576,
  "min_version": "1.0.0"
}
```

**构建脚本**（CI/手动）:
```bash
idf.py build
esptool.py --chip esp32s3 image_info build/app.bin  # 确认版本
# 可选签名
esptool.py --chip esp32s3 sign_data --keyfile signing.key build/app.bin
cp build/app.bin /var/www/ota/firmware/v1.2.0.bin
# 更新 manifest.json
```

## 六、开发期免烧录路径（Phase 1 → Phase 2）

| 阶段 | 方案 | 说明 |
|---|---|---|
| **Phase 1 开发期** | **ArduinoOTA** | IDE 无线烧录，迭代最快；无签名但内网开发足够 |
| **Phase 2 稳定期** | esp_https_ota | 双分区 + rollback + HTTPS，正式部署 |

> 建议: 开发期先 ArduinoOTA 快速迭代 UI/功能；功能冻结后切 esp_https_ota 跑完整 OTA 流程测试（含回滚演练）。

## 七、风险与缓解

| 风险 | 缓解 |
|---|---|
| eFuse 烧录不可逆 | 开发期不开 Secure Boot；生产前分阶段启用并保留密钥备份 |
| 回滚窗口过短（新固件启动慢）| 自检窗口可配（CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT，默认 5s，可调大）|
| 升级中断电 | ota_resumption 续传 + 双分区（写坏一个槽不影响当前运行槽）|
| 服务器不可达 | 启动不阻塞：OTA 检查放后台任务，失败静默重试（指数退避）|
| 固件版本回退 | manifest 的 min_version 限制；Secure Boot v2 的 anti-rollback（security version）|

## 八、待评估问题（交给高阶模型）

1. ArduinoOTA（Phase 1）与 esp_https_ota（Phase 2）切换时，分区表是否需要从 Arduino 的默认分区切换到 IDF 自定义分区？边界在哪？
2. Secure Boot v2 对开发期调试（JTAG、串口日志）的影响，如何最小化？
3. 8MB PSRAM 下 partial_http_download 是否值得？缓冲区策略？
4. 回滚自检项对"AI Agent Status 显示终端"这种弱交互应用，什么才算"自检通过"？（无传感器，仅 WiFi + 显示 + 触摸）
5. manifest.json 的签名（应用层校验）是否能作为 Secure Boot 之前的过渡方案？

---

## 引用来源

- [ESP-IDF OTA (ESP32-S3) 官方](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html)
- [ESP HTTPS OTA 官方](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/esp_https_ota.html)
- [ESP-IDF Secure Boot v2](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/security/secure-boot-v2.html)
- [esp_encrypted_img 组件](https://github.com/espressif/idf-extra-components/tree/master/esp_encrypted_img)
- [advanced_https_ota 示例](https://github.com/espressif/esp-idf/tree/master/examples/system/ota/advanced_https_ota)
