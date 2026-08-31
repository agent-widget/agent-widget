> Chinese version: [10-aw006-integrity-signing-rollback-e2e.zh-CN.md](./10-aw006-integrity-signing-rollback-e2e.zh-CN.md)

# 10 - AW-006: sha256 + RSA Signing + Periodic Check + UI Confirm + Rollback (Wokwi, simulated)

> Builds on [08-github-ota-simulation.md](./08-github-ota-simulation.md) (dual-channel GitHub OTA, semver). This document covers the AW-006 additions: periodic checking, UI/button confirmation, sha256 integrity verification, RSA-2048 publisher-signature verification, self-test-triggered rollback, and power-loss safety — plus the 5 destructive tests the brief required.
> Scope: Arduino/Wokwi simulation PoC, same boundary as document 08 — not ESP32-S3 production firmware.

---

## 1. What changed vs. document 08

| Area | 08 (baseline) | 10 (AW-006) |
|---|---|---|
| Check timing | On boot only | Boot + non-blocking periodic (`CHECK_INTERVAL_MS`, default 3600000ms) + serial `c` |
| Install trigger | Automatic | Gated behind UI/button/serial `u` confirmation — nothing is downloaded until the user confirms |
| Integrity | None | sha256 computed incrementally while streaming to flash, compared against a manifest-declared value; mismatch aborts before the boot pointer changes |
| Authenticity | None | RSA-2048 PKCS#1v1.5 signature (over the sha256 digest) verified against an embedded public key; mismatch aborts |
| UI | Serial only | ILI9341 (TFT_eSPI) screen: update-available prompt, download progress bar, verifying/success/rejected screens; pushbutton (GPIO27) as the physical confirm input |
| Rollback | None | Self-test-triggered automatic rollback via `arduino-esp32`'s built-in `CONFIG_APP_ROLLBACK_ENABLE` hook |
| Channel merge | "B only if A totally fails" | Always fetch both; Releases API (A) supplies the URL when present, manifest.json (B) always supplies sha256/signature — see key decision below |

---

## 2. Key design decisions

### 2.1 Where sha256/signature metadata lives
GitHub's Releases API has no field for custom per-asset metadata. Rather than smuggle it into release notes text, `manifest.json` (channel B) became the integrity-metadata index for **every** version, including ones whose bytes are served from a Releases API asset URL (channel A). The device now always fetches both channels and merges them by version: channel A's URL wins when present (keeps Releases as the "production primary channel" per the brief), channel B always supplies `sha256`/`signature`. Existing v1.0.0/v2.0.0 manifest entries were backfilled with sha256+signature computed from their real, already-published bytes (not local rebuilds — `arduino-cli`'s output is not byte-reproducible across runs; the real v2.0.0 Release asset's sha256 was confirmed by downloading it, not by rebuilding locally).

### 2.2 Rollback uses the core's built-in hook, not hand-rolled esp_ota_ops calls
`arduino-esp32` 3.3.11 ships `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=1` by default and a weak `bool verifyOta()` hook in `initArduino()` (runs before `setup()`): if the running partition is `ESP_OTA_IMG_PENDING_VERIFY`, it calls `verifyOta()` and, on `false`, calls `esp_ota_mark_app_invalid_rollback_and_reboot()` itself. The sketch overrides `verifyOta()` to run a bounded WiFi-connect self-test (or force-fail, for the rollback-drill build variant via `SELFTEST_FORCE_FAIL`). No manual `esp_ota_ops` bookkeeping needed in `loop()`.

### 2.3 "Not written to flash" on rejection
On sha256/signature failure the code calls `Update.abort()`, not `Update.end()`. Bytes may have transiently occupied the *inactive* OTA slot during download, but the otadata boot pointer is never updated, so the rejected image can never execute — this is the accurate technical meaning of "reject, don't install" on a dual-slot OTA layout.

### 2.4 UI text is English, not the literal Chinese wording in the brief
`TFT_eSPI`'s default fonts have no CJK glyphs; drawing the brief's example Chinese string as-is would render as boxes/garbage. The functional requirement (a legible on-screen upgrade prompt/progress/result) is met with English text instead. Loading a CJK bitmap font for `TFT_eSPI` is a viable follow-up, not attempted here.

---

## 3. Firmware / device flow

```
boot → verifyOta() (only if PENDING_VERIFY) → connect Wokwi-GUEST → begin_check()
  → fetch Releases API (A) + manifest.json (B), merge by version
  → pick target (OTA_TARGET_VERSION: "latest" or pinned) → target > current?
      no  → idle, heartbeat, wait for next periodic check
      yes → ST_AVAILABLE: TFT prompt + serial "[OTA] UPDATE AVAILABLE"
            → wait for button press / serial 'u'
            → ST_DOWNLOADING: stream to flash via Update.write(), sha256 incremental update, TFT progress bar
            → ST_VERIFYING: compare sha256; if mismatch → Update.abort(), ST_FAILED
                              verify RSA signature over the sha256 digest; if invalid → Update.abort(), ST_FAILED
            → ST_APPLYING: Update.end(true) → ESP.restart()
  new image boots → PENDING_VERIFY → verifyOta() self-test
      pass → esp_ota_mark_app_valid_cancel_rollback(), normal operation
      fail → esp_ota_mark_app_invalid_rollback_and_reboot() → reboots back onto the previous image
```

---

## 4. Destructive test results

Reproduction: `wokwi-run/scenarios/*.json` + `node run_ota_test.js <scenario>.json` (serial-driven confirm) or `run_ota_ui.js <scenario>.json` (physical pushbutton click + ILI9341 screenshots). Evidence: `wokwi-run/evidence/`.

<!-- RESULTS_TABLE_PLACEHOLDER -->

### How each bad fixture was constructed (reproducible)
- **v3.0.1 (test 2, bad sha256)**: real firmware bytes are fine; `firmware/manifest.json`'s `sha256` for this version has its last hex nibble flipped vs. the actual `sha256sum` of `firmware/releases/v3.0.1.bin` (`...ec0` → declared `...ec1`). Reproduce: `./sign_firmware.sh <bin>`, then hand-edit one hex character before calling `update_manifest.py`.
- **v3.0.2 (test 3, bad signature)**: sha256 is correct; the signature was produced with a throwaway "attacker" RSA keypair instead of the trusted dev keypair whose public half is embedded in the sketch (`ota_pubkey.h`). Reproduce: `openssl genrsa -out attacker.pem 2048`, then `./sign_firmware.sh <bin> attacker.pem`.
- **v3.0.3 (test 4, self-test failure)**: correctly signed and hashed; built with `SELFTEST_FORCE_FAIL_OVERRIDE=1 ./build_arduino.sh 3.0.3`, which forces `verifyOta()` to return `false` unconditionally on first boot.
- **Test 5 (power loss)**: no special fixture — reuses the good v3.0.0 target. The driver script clicks Wokwi's "Restart the simulation" (a warm MCU reset, not a full teardown) once download progress crosses a threshold, before `Update.end()` is ever reached.

---

## 5. What AW-006 does not cover (production gap, unchanged from doc 08 §7)

Same production gaps as before: ESP-IDF firmware, `esp_https_ota`, factory+ota_0+ota_1 partitioning, real-device verification, Secure Boot/Flash Encryption. Additionally now: the `OTA_SIGNING_KEY` GitHub Actions secret does not exist yet (human action — see `docs.local/operations/ota-e2e-claude-report.md` follow-ups), and the on-screen UI text is English, not localized.
