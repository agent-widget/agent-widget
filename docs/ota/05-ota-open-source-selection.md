> Chinese version: [05-ota-open-source-selection.zh-CN.md](./05-ota-open-source-selection.zh-CN.md)

# 05-Mature Open-Source OTA Solution Selection (prefer adoption, don't reinvent the wheel)

> Date: 2026-08-22
> Principle: when a good open-source / mature solution exists, don't build our own wheel (explicit user instruction)
> Update: this document replaces the self-built pipeline idea in 02; the "self-hosted OTA pipeline" recommendation of 04 is replaced by the open-source solution in this document

---

## 0. Architecture Boundary (updated 2026-08-24, read first)

> ⚠️ The **SafeGithubOTA / esp32FOTA** selected in this document are both **Arduino-ecosystem libraries**. The project's formal firmware target is **ESP-IDF** (per the project's operating contract and `docs/hardware/board-spec-constraints.md`). Therefore:
> - The conclusion of this section is a reference for **Arduino rapid prototyping during development** and **must not** be used as the production OTA implementation for AW-006.
> - The AW-006 production implementation must use **ESP-IDF** (`esp_https_ota` / `advanced_https_ota`) + GitHub Releases distribution + `factory + ota_0 + ota_1` dual-slot + explicit failure rollback + factory recovery trigger.
> - Touch self-check uses **AXS15231B (I2C 0x3B)**, not FT6336U.

---

## 1. Conclusion First

**Recommended primary solution: [SafeGithubOTA](https://github.com/gibz104/SafeGithubOTA) (MIT) — GitHub Releases hosting + automatic rollback + validation callback + zero self-hosted server.**

**Alternative/enhancement: [esp32FOTA](https://github.com/chrisjoyce911/esp32FOTA) (LGPL) — when firmware RSA signature verification or a self-hosted server is needed.**

**Official fallback: esp_https_ota + advanced_https_ota example (when full self-control / intranet OTA is needed).**

No need to build a custom "download → verify signature → esp_ota_write" pipeline — SafeGithubOTA already wraps the complete flow (download → flash → rollback), and esp32FOTA already implements signature verification.

---

## 2. Deep Comparison of the Two Core Candidates

| Dimension | **SafeGithubOTA** ⭐ | **esp32FOTA** |
|---|---|---|
| License | MIT | LGPL |
| Hosting | **GitHub Releases** (free, public internet) | Self-hosted HTTP/HTTPS server (manifest.json) |
| Firmware source verification | HTTPS (GitHub TLS + optional PAT for private repos) | **RSA 4096 signature verification** (check_sig, strictest) |
| Brick-proof rollback | ✅ **Automatic rollback** (bootloader dual partition + validation callback) | ⚠️ No built-in rollback (must configure dual partition + rollback API yourself) |
| Version comparison | ✅ semver (MAJOR.MINOR.PATCH) | ✅ semver (semver.c) |
| Initial configuration | ✅ **Captive Portal** (WiFi AP + web form, stored in NVS) | ❌ Manually hard-coded manifest URL |
| Automatic check | ✅ Timer (e.g., every 6h) | ✅ handle() polling |
| Progress callback | ✅ onProgress | ✅ setProgressCb (can drive a TFT progress bar) |
| Validation callback | ✅ onValidation (confirms firmware only if self-check passes) | ❌ None (relies on signature + reboot) |
| Rollback detection | ✅ wasRolledBack() | ❌ |
| Dependencies | **Zero external dependencies** (built into the Arduino core) | semver.c + optional compression library |
| Filesystem update | ❌ (firmware only) | ✅ spiffs/littlefs/fatfs images |
| Compressed firmware | ❌ | ✅ zlib/gzip (saves bandwidth) |
| Best fit | Development phase + small-scale production (has a GitHub account) | Self-hosted server + strong signature required + large firmware bandwidth savings |

## 3. Selection Logic (why SafeGithubOTA first)

1. **No self-hosted server**: GitHub Releases is the OTA server — publishing firmware = create a tag + upload the .bin, the least effort during development
2. **Automatic rollback out of the box**: if the validation callback (e.g., "LVGL renders successfully + touch I2C ACK + WiFi connects") returns false → automatic rollback, exactly what the 04 evaluation required with "explicit rollback on self-check timeout/failure" — the library already encapsulates it
3. **Captive Portal avoids manual configuration**: on first boot the device opens a WiFi AP with a web page to fill in the repository info, more elegant than a hard-coded URL (and matches the "Wi-Fi provisioning phase 2" idea in 02)
4. **Zero dependencies**: only uses WiFi/WiFiClientSecure/WebServer/Update/Preferences — compiles directly with PlatformIO/Arduino
5. **GitHub private repo + PAT** optional; public repos don't even need a token (60 req/h rate limit is enough)

### Where esp32FOTA adds value
- When **firmware-level signature verification** is needed (the strongest protection against unauthorized sources, beyond HTTPS transport protection), esp32FOTA's RSA 4096 signature is ready-made — far simpler than a self-built "manifest signature"
- When an **intranet/self-hosted server** is needed (device cannot reach the public internet), the manifest.json mode is more flexible
- When **compressed firmware** is needed (saves 50-70% bandwidth)

### Where the official esp_https_ota adds value
- When you need full control of upgrade timing / resumable downloads / pre-encrypted firmware, the official advanced_https_ota example (version check + anti-rollback + resumption) is a production-grade baseline

---

## 4. Recommended Implementation Path (revising the 02 plan)

```
Phase 1 development (fast iteration without serial flashing):
  ArduinoOTA (wireless flashing directly from the IDE) → already the fastest
  or go straight to SafeGithubOTA (GitHub Releases as the server, no need to connect the IDE to the device)

Phase 2 stabilization (recommended):
  SafeGithubOTA
    - Release via GitHub Releases (tag = semver, attach .bin)
    - validation callback = display/touch/WiFi/OTA task self-check
    - automatic rollback + wasRolledBack() reporting
    - optional: PAT private repo

Phase 3 production enhancement (as needed):
  a) Firmware signing needed → esp32FOTA's RSA signature (or the official Secure Boot v2)
  b) Intranet/self-hosted server needed → esp32FOTA manifest mode or esp_https_ota
  c) Device management platform needed → OTA Hub DIY / pleasedontcode-style platforms (research alternatives)
```

## 5. Specific Adaptation for This Project (AI Agent Status display terminal)

**validation callback design** (SafeGithubOTA onValidation):

```cpp
ota.onValidation([]() -> bool {
    // Must pass: display/touch/WiFi/OTA task
    if (!display_init_ok()) return false;   // AXS15231B
    if (!touch_i2c_ok()) return false;      // AXS15231B (I2C 0x3B)
    if (WiFi.status() != WL_CONNECTED) return false;
    return true;  // WebSocket server unreachable is not a failure (can degrade)
});
```

**Partition table to configure** (for rollback):

- PlatformIO: `board_build.partitions = partitions_ota.csv`
- Dual OTA slots (ota_0/ota_1) + otadata (SafeGithubOTA's rollback depends on it)
- Reference the 16MB partition table from 02 (`nvs 0x8000 + otadata + factory + ota_0 + ota_1 + LittleFS`). ⚠️ **Keep the factory slot + explicit recovery trigger** (GPIO long-press or `esp_ota_set_boot_partition(factory)` after N consecutive failures), don't drop the factory fallback path (see `docs/ota/04-ota-evaluation-conclusion.md`, defect 2)

**Confirmed gotchas** (stated in the README):

- In the `.ino` you must `SET_LOOP_TASK_STACK_SIZE(16 * 1024)` (TLS needs it; the default 8KB will crash)
- `begin()` must be called after WiFi connects (it does NTP sync internally; TLS certificate verification needs an accurate clock)
- PAT is stored in plaintext in NVS (note when using a private repo)

---

## References

- [SafeGithubOTA (gibz104)](https://github.com/gibz104/SafeGithubOTA) | MIT | GitHub Releases OTA + rollback + captive portal
- [esp32FOTA (chrisjoyce911)](https://github.com/chrisjoyce911/esp32FOTA) | LGPL | manifest OTA + RSA signature
- [ESP32 OTA topic page (GitHub topics)](https://github.com/topics/ota-firmware-updates) | esp_ghota / mcm-esp32-ota-fw-updater / OTA Hub DIY, etc.
- [ubirch-esp32-ota](https://github.com/ubirch/ubirch-esp32-ota) | IDF component, certificate directory
- [ESP-IDF advanced_https_ota example](https://github.com/espressif/esp-idf/tree/master/examples/system/ota/advanced_https_ota) | Official: version check + anti-rollback + resumption
- [ESPHome OTA](https://esphome.io/components/ota/esphome/) | production-grade reference (password + safe mode)
- [Tasmota OTA](https://tasmota.github.io/docs/Upgrading/) | production-grade reference
- [SafeGithubOTA README full API](https://github.com/gibz104/SafeGithubOTA#readme)
