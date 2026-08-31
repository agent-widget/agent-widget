> Chinese version: [01-ota-alternatives-comparison.zh-CN.md](./01-ota-alternatives-comparison.zh-CN.md)

# 01-ESP32-S3 OTA Options Research and Comparison

> Date: 2026-08-22
> Hardware: Waveshare ESP32-S3-Touch-LCD-3.5B (ESP32-S3R8, 8MB PSRAM / 16MB Flash)
> Purpose: Design an OTA approach — no re-flashing during later development + fault tolerance against bricking + firmware verification against unauthorized sources/incomplete files
> Status: Research complete, options compared, awaiting selection and refinement

---

## 1. Requirements Summary

| Requirement | Description |
|---|---|
| No frequent re-flashing | Update firmware over Wi-Fi during development/deployment, no USB cable needed |
| Fault tolerance, no bricking | A new firmware that fails automatically rolls back to the last working version |
| Firmware verification | Reject unauthorized sources (signature verification) and incomplete firmware (integrity checks) |
| Usability | Simple during development, reliable in production, balancing both |

## 2. Overview of Candidate Options

### Option A: ArduinoOTA / ElegantOTA (development phase)
- **How it works**: Arduino library; upload firmware to the device directly from the IDE or a web page
- **Pros**: extremely simple, 5-minute setup during development
- **Cons**: ❌ no signature verification (anyone can upload), ❌ no automatic rollback (depends on the partition table), ❌ tied to the Arduino ecosystem

### Option B: ESP-IDF Native OTA (dual partitions + rollback) ⭐
- **How it works**: official app_update component; ota_0/ota_1 dual partitions + otadata partition + `esp_ota_mark_app_valid_cancel_rollback()`
- **Flow**: download the new firmware into the idle partition → verify → switch the boot partition → reboot → new firmware self-checks → on success mark valid, on failure roll back automatically
- **Pros**: ✅ officially maintained, ✅ automatic rollback prevents bricking, ✅ Secure Boot v2 signature verification, ✅ flexible (HTTP/HTTPS both work)
- **Cons**: steep ESP-IDF learning curve; extra configuration required under the Arduino framework

### Option C: esp_https_ota (simplified HTTPS) ⭐
- **How it works**: an HTTPS abstraction layer on top of app_update; `esp_https_ota()` completes download + write + partition switch in one call
- **Pros**: ✅ official component, ✅ built-in TLS server verification (cert_pem), ✅ OTA resumption support, ✅ partial download support (saves RAM), ✅ event system for monitoring progress
- **Cons**: needs an HTTPS server (mTLS or self-signed certificates work for local development); under the Arduino framework use the `Update` class or the IDF component

### Option D: Secure Boot v2 + Flash Encryption (production-grade security) ⭐
- **How it works**: burn eFuse at factory flashing → bootloader verifies the signature → firmware stored encrypted
- **Pros**: ✅ strongest protection against unauthorized sources (hardware-level signature verification), ✅ prevents firmware extraction
- **Cons**: ❌ **burning eFuse is irreversible** (one-time decision), ❌ requires key management, ❌ constrained development/debugging (only signed firmware can run)

### Option E: Custom Server + Version Check + Manifest File (application layer)
- **How it works**: the device polls the HTTP server → downloads manifest.json (version/hash/URL) → verifies the hash → downloads the firmware
- **Pros**: fully controllable, no framework dependency
- **Cons**: reinventing the wheel; no official rollback state machine support (must be implemented yourself)

### Option F: Delta Updates (Delta OTA)
- **How it works**: download only the difference between the old and new firmware (Xdelta, etc.)
- **Pros**: ✅ saves bandwidth (noticeable for large firmware)
- **Cons**: requires server-side diff computation + client-side merging, high complexity, **limited benefit in the 16MB Flash scenario**

## 3. Side-by-Side Comparison

| Dimension | A: ArduinoOTA | B: IDF Native | C: esp_https_ota | D: Secure Boot | E: Custom Manifest | F: Delta |
|---|---|---|---|---|---|---|
| Anti-brick rollback | ❌ none | ✅ automatic | ✅ automatic | ✅ automatic | ⚠️ self-implemented | ✅ depends on B/C |
| Reject unauthorized sources | ❌ | ✅ (SBv2) | ✅ (HTTPS) | ✅✅ (hardware) | ⚠️ hash | ✅ (SBv2) |
| Reject incomplete firmware | ⚠️ partial | ✅ verified | ✅ verified + resumption | ✅ | ✅ hash | ✅ |
| Development ease | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐ |
| Production reliability | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| Official support | Arduino library | ✅ | ✅ | ✅ | ❌ | community |
| Best-fit phase | development | all | all | production | custom | large firmware |

## 4. Selection Recommendation (my analysis)

**Recommended combination: Option B (IDF native OTA with dual partitions + rollback) as the backbone, Option C (esp_https_ota) as the transport layer, and Option D (Secure Boot v2) as a production-phase enhancement.**

Reasons:
1. **Development phase** (no re-flashing): start with ArduinoOTA for fast iteration → switch to esp_https_ota once the firmware is stable
2. **Production phase** (reliability): the IDF native OTA rollback state machine is the officially validated anti-brick core; esp_https_ota provides HTTPS transport security + resumption
3. **Security enhancement**: Secure Boot v2 signature verification completely eliminates unauthorized firmware — but **the decision must be made at first flashing** (eFuse is one-time); it can stay off during development and be enabled before release

### Why not delta updates
With a 16MB Flash partition table giving ota_0/ota_1 4MB each, there is ample room; firmware is typically <2MB, so the delta benefit (saving a few MB of transfer) does not justify introducing server-side diff complexity.

---

## References

- [ESP-IDF OTA official docs (ESP32-S3)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html)
- [ESP HTTPS OTA official docs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/esp_https_ota.html)
- [Maker Gear Lab: Firmware Rollback Mechanism](https://makergearlab.com/developing-a-firmware-rollback-mechanism-for-esp32-devices-after-failed-ota-updates/)
- [IOT Journal: Prevent Bricking Field Devices](https://www.iotjournal.ir/esp32-ota-update-guide-how-to-prevent-bricking-field-devices/)
- [SunFounder: ArduinoOTA & ElegantOTA Guide](https://www.sunfounder.com/blogs/news/esp32-ota-updates-a-complete-guide-to-arduinoota-and-elegantota-firmware-upgrades)
- [Zhihu: ESP32 HTTPS OTA Upgrade](https://zhuanlan.zhihu.com/p/721592546)
- [Juejin: Engineering practice from ESP32 dual partitions to delta updates](https://juejin.cn/post/7671153017659654207)
