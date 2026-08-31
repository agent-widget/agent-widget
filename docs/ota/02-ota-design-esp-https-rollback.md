> Chinese version: [02-ota-design-esp-https-rollback.zh-CN.md](./02-ota-design-esp-https-rollback.zh-CN.md)

# 02-OTA Detailed Design: esp_https_ota + Dual-Partition Rollback + Secure Boot v2

> Date: 2026-08-22
> Based on: 01-ota-alternatives-comparison.md (selection conclusion)
> Hardware: ESP32-S3-Touch-LCD-3.5B (16MB Flash / 8MB PSRAM)
> Status: Design draft (v0.1)
> ⚠️ Update (2026-08-22): **the custom pipeline design in this draft has been superseded by the open-source options in 05-ota-open-source-selection.md** (SafeGithubOTA / esp32FOTA). This draft is kept as a reference for the principles (the partition table/state machine/self-check design is still valuable); implementation follows 05.

---

## 1. Target Architecture

```
┌────────────┐   HTTPS    ┌──────────────────┐
│ OTA Server │◀──────────▶│  ESP32-S3 Device │
│ (static)   │   pull      │  ┌─────────────┐ │
│  firmware/ │   firmware  │  │ App (LVGL)  │ │
│  latest.bin│            │  └──────┬──────┘ │
│  manifest. │            │  esp_https_ota   │
│  json      │            │  └──────┬──────┘ │
└────────────┘            │  ota_0 / ota_1   │
                          │  (dual slots +   │
                          │  rollback)       │
                          └──────────────────┘
```

**Core components**:
1. **Partition table**: ota_0 + ota_1 dual app partitions + otadata + NVS (stores OTA state)
2. **Transport**: HTTPS (esp_https_ota, verifies the server certificate)
3. **Verification**: firmware signature (Secure Boot v2, optional production enhancement) + firmware header check (app_desc version)
4. **Rollback**: IDF native rollback state machine (PENDING_VERIFY → VALID / INVALID)

---

## 2. Partition Table Design (16MB Flash)

```
# Name,   Type, SubType, Offset,  Size,   Flags
nvs,      data, nvs,     0x9000,  0x6000,
otadata,  data, ota,     0xf000,  0x2000,
phy_init, data, phy,     0x11000, 0x1000,
factory,  app,  factory, 0x20000, 0x400000,   # factory firmware (4MB)
ota_0,    app,  ota_0,   0x420000, 0x400000,  # OTA slot A (4MB)
ota_1,    app,  ota_1,   0x820000, 0x400000,  # OTA slot B (4MB)
storage,  data, spiffs,  0xc20000, 0x3E0000,  # resources/fonts/config
```

**Key points**:
- 16MB Flash is ample: 3 × 4MB app slots + 4MB storage (SPIFFS for LVGL font/image resources)
- Keep the factory slot as the last resort (can jump back to factory firmware)
- otadata records the `ota_seq` counter + state (IDLE/PENDING_VERIFY/VALID/INVALID)

## 3. Firmware Update Flow (State Machine)

```
[Boot] → check otadata
  ├─ PENDING_VERIFY → self-check (below)
  │    ├─ self-check passes → esp_ota_mark_app_valid_cancel_rollback() → VALID
  │    └─ self-check fails/times out → esp_ota_mark_app_invalid_rollback_and_reboot() → rollback
  └─ VALID → normal operation → periodically check for updates

[Check for updates] → fetch manifest.json
  ├─ version ≤ current → skip
  └─ version > current → esp_https_ota downloads to the idle partition
       ├─ download complete → verify (signature/hash) → esp_restart()
       └─ failure → keep the old firmware, retry next time
```

### Self-check (PENDING_VERIFY phase, the key anti-brick measure)

On first boot the new firmware enters the PENDING_VERIFY state and must complete the following within the timeout window:

| Check | Method |
|---|---|
| Basic boot | No crash within 30 seconds of startup (task watchdog as fallback) |
| Display init | LVGL + AXS15231B initialize successfully |
| Touch init | AXS15231B (I2C 0x3B) communication works |
| Wi-Fi connection | Connects to the AP within the allotted time |
| Critical services | OTA check task stays alive |
| Version self-report | app_desc.version matches the manifest |

If all pass → `esp_ota_mark_app_valid_cancel_rollback()`; if any fails or times out → **explicitly call `esp_ota_mark_app_invalid_rollback_and_reboot()` to roll back to the previous slot**. ⚠️ Do not rely on a hardware watchdog reset to trigger rollback (IDF automatic rollback only happens after a crash/WDT reset while the state is still PENDING_VERIFY; if mark_valid is mistakenly called early, or the device hangs without any reset, no rollback occurs). mark_valid must only be called after all self-checks pass.

## 4. Transport and Verification Details

### 4.1 HTTPS Transport (esp_https_ota)

```c
esp_http_client_config_t http_config = {
    .url = "https://ota.example.com/firmware/latest.bin",
    .cert_pem = (char *)server_root_cert_pem,   // server root certificate (embedded)
    .timeout_ms = 30000,
};
esp_https_ota_config_t ota_config = {
    .http_config = &http_config,
    .ota_resumption = true,    // resume interrupted downloads
};
esp_err_t ret = esp_https_ota(&ota_config);
if (ret == ESP_OK) esp_restart();
```

**Feature usage**:
- `cert_pem`: trust only our own server (self-signed root certificate burned into the firmware), preventing man-in-the-middle/unauthorized sources
- `ota_resumption`: after an interrupted download, resume from the last position (stored in NVS), avoiding repeated full downloads
- `partial_http_download`: download large firmware in chunks to save RAM (not required but optional with 8MB PSRAM)
- Event system: listen for `ESP_HTTPS_OTA_*` events to drive the UI progress bar (LVGL shows the update progress)

### 4.2 Firmware Verification (dual-layer)

| Layer | Mechanism | Protects against |
|---|---|---|
| **Transport layer** | HTTPS + server certificate verification | Man-in-the-middle / fake server |
| **Signature layer** (Secure Boot v2) | Firmware RSA/ECDSA signature | Unauthorized firmware (non-official builds) |
| **Integrity** | esp_ota built-in image verification (header + hash) | Corrupted/truncated downloads |

### 4.3 Secure Boot v2 (enabled in production)

- At first flashing, burn the signing public key with `idf.py efuse burn-key`; after that the bootloader only runs firmware whose signature matches
- **⚠️ eFuse is one-time**: confirm before enabling — during development use soft verification (verify the manifest signature at the application layer), and enable the hardware mechanism before the production release
- Signing flow: `idf.py signed-app` → generates `.signed.bin` → upload to the server

## 5. OTA Server Design (minimal viable setup for development)

```bash
# Simple static server (nginx or python http.server + HTTPS)
/var/www/ota/
├── manifest.json          # {version, url, sha256, size}
└── firmware/
    └── v1.2.0.bin         # build artifact
```

**manifest.json structure**:
```json
{
  "version": "1.2.0",
  "url": "https://ota.example.com/firmware/v1.2.0.bin",
  "sha256": "a1b2c3...",
  "size": 1048576,
  "min_version": "1.0.0"
}
```

**Build script** (CI/manual):
```bash
idf.py build
esptool.py --chip esp32s3 image_info build/app.bin  # confirm the version
# optional signing
esptool.py --chip esp32s3 sign_data --keyfile signing.key build/app.bin
cp build/app.bin /var/www/ota/firmware/v1.2.0.bin
# update manifest.json
```

## 6. No-Re-Flash Path During Development (Phase 1 → Phase 2)

| Phase | Option | Description |
|---|---|---|
| **Phase 1, development** | **ArduinoOTA** | Wireless flashing from the IDE, fastest iteration; no signing, but sufficient for LAN development |
| **Phase 2, stable** | esp_https_ota | Dual partitions + rollback + HTTPS, for formal deployment |

> Recommendation: use ArduinoOTA during development for fast UI/feature iteration; after feature freeze, switch to esp_https_ota to run the full OTA flow tests (including a rollback drill).

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| eFuse burning is irreversible | Keep Secure Boot off during development; enable in stages before production and keep key backups |
| Rollback window too short (new firmware boots slowly) | Self-check window is configurable (CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT, 5s default, can be increased) |
| Power loss during update | ota_resumption resume + dual partitions (corrupting one slot does not affect the currently running slot) |
| Server unreachable | Boot never blocks: OTA check runs in a background task; failures retry silently (exponential backoff) |
| Firmware version downgrade | manifest's min_version constraint; Secure Boot v2 anti-rollback (security version) |

## 8. Open Questions (for a higher-capability model to evaluate)

1. When switching from ArduinoOTA (Phase 1) to esp_https_ota (Phase 2), does the partition table need to change from the Arduino default to an IDF custom table? Where is the boundary?
2. How does Secure Boot v2 affect development debugging (JTAG, serial logs), and how can the impact be minimized?
3. With 8MB PSRAM, is partial_http_download worthwhile? What buffer strategy?
4. For a weakly interactive application like an AI Agent Status display terminal, what counts as "self-check passed"? (no sensors, only Wi-Fi + display + touch)
5. Can manifest.json signing (application-layer verification) serve as an interim solution before Secure Boot?

---

## References

- [ESP-IDF OTA (ESP32-S3) official](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html)
- [ESP HTTPS OTA official](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/esp_https_ota.html)
- [ESP-IDF Secure Boot v2](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/security/secure-boot-v2.html)
- [esp_encrypted_img component](https://github.com/espressif/idf-extra-components/tree/master/esp_encrypted_img)
- [advanced_https_ota example](https://github.com/espressif/esp-idf/tree/master/examples/system/ota/advanced_https_ota)
