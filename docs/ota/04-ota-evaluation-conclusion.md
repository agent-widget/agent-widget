> Chinese version: [04-ota-evaluation-conclusion.zh-CN.md](./04-ota-evaluation-conclusion.zh-CN.md)

# 04-OTA Design Evaluation Conclusion (Consolidated)

> Date: 2026-08-22
> Evaluating model: deepseek-v4-pro (reasoning model; the 57K-character evaluation transcript is in doc 03)
> Evaluated artifact: 02-ota-design-esp-https-rollback.md
> This document: structured conclusions distilled from the raw reasoning trace in 03
> ⚠️ Update (2026-08-22): the evaluation targeted the 02 custom design. After the user instructed "use mature options, don't reinvent the wheel", implementation moved to the open-source options (see 05-ota-open-source-selection.md). The **defect insights in this document remain valuable** — use them to check whether the open-source options cover these points during selection (e.g. SafeGithubOTA already covers defect 1's integrity check + defect 3's rollback timing; keeping the factory fallback from defect 2 is still recommended).

---

## 1. Overall Conclusion

**The design is feasible but conditional; v0.1 cannot go to production as-is.** The architectural direction is sound (esp_https_ota + dual-partition rollback + Secure Boot v2 layering), but there are 3 critical defects that must be fixed, plus several supplementary items.

---

## 2. Critical Defects (ordered by severity)

### Defect 1: the manifest's sha256 is never actually verified (integrity gap)

- **Problem**: in the design flow "fetch manifest → version check → esp_https_ota download", the `sha256` field in `manifest.json` is **just decorative** — the code example downloads `latest.bin` directly without verifying the manifest signature or the firmware hash
- **Risk**: relying on HTTPS transport security ≠ firmware integrity. If the server is compromised, CI publishes by mistake, or a download is truncated, a bad firmware gets written straight into the OTA slot
- **Fix**: build a custom OTA pipeline at the application layer: HTTP download → temporary area (PSRAM/SPIFFS) → verify the manifest signature (RSA/ECDSA, embedded public key) + SHA256 → only then `esp_ota_write` to the target partition. Or read back and verify before rebooting after the download

### Defect 2: the factory fallback partition has no trigger path

- **Problem**: the partition table defines a factory slot, but **no code path can jump back to factory**. If both ota_0 and ota_1 are corrupted, the bootloader only auto-selects factory when otadata is invalid — but the normal flow never triggers it
- **Fix**: add a recovery mechanism:
  - Option a: long GPIO press (e.g. hold the BOOT button 5s) → the application calls `esp_ota_set_boot_partition(factory_partition)` → reboot
  - Option b: N consecutive failed boots → NVS counter → automatically jump to factory
  - Make the factory firmware a "minimal OTA recovery firmware" (Wi-Fi + OTA only); this is the standard production-grade strategy

### Defect 3: misconception about rollback timing (the core anti-brick issue)

- **Problem**: the design says "self-check fails/times out → hardware watchdog reset → bootloader auto-rollback", but **IDF automatic rollback does not work that way**:
  - Automatic rollback triggers only when: after the new firmware **crashes/WDT resets**, the bootloader detects the state is still `PENDING_VERIFY`
  - If the code mistakenly calls `esp_ota_mark_app_valid_cancel_rollback()` before the self-check, a later crash **will not roll back**
  - If the new firmware hangs without producing any reset (no WDT), it will not roll back either
- **Fix**:
  - Explicitly set a self-check timeout timer (e.g. 30-60s); the timeout/failure path must call `esp_ota_mark_app_invalid_rollback_and_reboot()`
  - Call mark_valid **only after all self-checks pass**, never early
  - Enable `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` + task WDT

---

## 3. Answers to the Five Open Questions

### Q1: Where is the partition-table switch boundary between ArduinoOTA (Phase 1) and esp_https_ota (Phase 2)?

**Answer**: the boundary is in the **board-level partition table configuration**, not in code.
- ArduinoOTA uses the Arduino `Update` class and requires the PlatformIO config `board_build.partitions = custom_partitions.csv`
- No partition-table switch is needed from Phase 1 to Phase 2 — **use the final partition table from the start** (with factory/ota_0/ota_1); ArduinoOTA writes the OTA slot and esp_https_ota writes the OTA slot too, so the two are compatible
- Key point: during development ArduinoOTA uploads unsigned firmware → Secure Boot v2 must be enabled **last**

### Q2: How does Secure Boot v2 affect development debugging?

**Answer**:
- After enabling: every flashed app (including factory/ota_0/ota_1) must be signed or it will refuse to boot
- JTAG debugging still works (Secure Boot does not lock JTAG; only Flash Encryption does)
- Serial logs are unaffected
- Strategy to minimize the impact: do not enable it at all during development; before release, burn the eFuse in one shot and flash signed firmware into all slots. **The eFuse is irreversible — back up the keys first**

### Q3: With 8MB PSRAM, is partial_http_download worthwhile?

**Answer**: **not worthwhile as a default**. The default mbedTLS Rx buffer of 16KB is sufficient; partial mode only saves ~12KB of RAM — meaningless with 8MB PSRAM, and it adds code complexity (chunked requests).
- Keep the default (single streaming download request)
- The real value of 8MB PSRAM: the download buffer can be enlarged (e.g. 32-64KB) to improve throughput

### Q4: For a display terminal (no sensors), what counts as "self-check passed"?

**Answer** (local critical paths matter):
- **Must pass**: RTOS boot, LVGL initialization and rendering a local test page, backlight, touch I2C ACK, Wi-Fi STA connection with IP obtained, OTA task alive
- **Degradable**: WebSocket server connection/receiving messages — **server unreachability should not cause a rollback** (otherwise a cloud outage would mark good firmware as bad)
- Flow: 30-60s of stability after boot without reset; hardware/init failure → mark_invalid_rollback; remote service failure only logs, does not fail
- Recommendation: design a "minimum local UI" that displays device status; a successful render proves display/touch work

### Q5: Can manifest signing be an interim solution before Secure Boot?

**Answer**: **yes, with conditions**. At minimum:
- Manifest signing (RSA/ECDSA, embedded public key)
- Firmware sha256 verified **before** writing to the OTA partition
- Monotonic version increase / no downgrade (min_version)
- Anti-replay: the manifest carries issued_at/nonce, freshness check
- HTTPS pinned CA

⚠️ Note: application-layer verification cannot prevent custom firmware flashed via UART/JTAG (it only protects the OTA channel); and sha256 verification is awkward when esp_https_ota writes while downloading — a custom pipeline is recommended: download to a temporary area → verify signature + SHA256 → esp_ota_write.

---

## 4. Supplementary Gaps Worth Noting

1. **Partition table fix** (recommended): enlarge nvs to 0x8000 (more room for OTA resumption + Wi-Fi state); use **LittleFS** for storage (SPIFFS is marginalized in IDF); keep the partition-table offset at 0x8000
2. **Power/dropout**: OTA download is a power peak (Wi-Fi + flash writes); call `esp_wifi_set_ps(WIFI_PS_NONE)` during the download to avoid disconnects, and confirm stable power before writing flash (brownout detector); with battery power, forbid OTA when charge is low
3. **Flash wear**: with ota_resumption, do not write NVS on every chunk; save the offset periodically or only on interruption
4. **Certificate rotation**: cert_pem should embed the root CA (not the leaf certificate); reserve a rotation mechanism (a manifest-issued new public key requires manifest signing, or burn two root certificates)
5. **Asset versioning**: storage partition resources (fonts/images) may be incompatible with the firmware version — assets need version numbers, and rollback should avoid old and new firmware sharing incompatible resources
6. **Diagnostics**: keep boot count / crash reason / OTA state in NVS for rollback cause analysis (telemetry)
7. **Anti-rollback risk**: a wrongly set Secure Boot v2 security version can brick the device — min_version must align with the security version

---

## 5. Revised Recommended Flow (v0.2 direction)

```
Check for updates
  → fetch manifest over HTTPS (signature verification + freshness check)
  → version > current?
  → download firmware to a temporary area (PSRAM/SPIFFS)
  → verify sha256 + signature
  → esp_ota_write to the unused slot
  → reboot (bootloader sets PENDING_VERIFY)
  → self-check (30-60s: display/touch/Wi-Fi/OTA task)
  → all pass → mark_valid | fail/timeout → mark_invalid_rollback
  → N consecutive failures / long GPIO press → jump to factory recovery firmware
```

---

## References

- [03-ota-design-evaluation.md](./03-ota-design-evaluation.md) | deepseek-v4-pro raw evaluation (57K chars)
- [02-ota-design-esp-https-rollback.md](./02-ota-design-esp-https-rollback.md) | the evaluated design draft
- [ESP-IDF OTA official](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/ota.html)
