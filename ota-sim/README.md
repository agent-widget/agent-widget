# ota-sim — GitHub OTA source for the simulation phase (Arduino PoC)

> This directory is the reproducible source for the "GitHub OTA simulation" (docs/ota/08), built by the GitHub Actions release pipeline.
> **Boundary:** Arduino-ecosystem PoC, not ESP32-S3 production firmware. This directory will be removed once production AW-006 lands (ESP-IDF + esp_https_ota).

## Files

| File | Description |
|---|---|
| `sketch_gh_ota.ino` | Version-aware OTA client (FW_VERSION / OTA_TARGET_VERSION injected at compile time; GitHub Releases API primary channel + manifest.json fallback) |
| `build_arduino.sh` | arduino-cli local build (esp32 core 3.x + custom dual-slot OTA partition table; `./build_arduino.sh <ver> [out_dir]`) |
| `custom_partitions.csv` | OTA partition table (nvs/otadata/app0/app1/spiffs, matching the Wokwi simulator) |
| `build_gh.py` | (Fallback) builds via the Wokwi cloud build API, for simulator verification |
| `update_manifest.py` | Updates `firmware/manifest.json` (`python3 update_manifest.py <ver> <url> <size> <path> [sha256] [signature_b64]`) |
| `gen_keys.sh` | AW-006: generates (or reuses) the dev RSA-2048 signing keypair under `keys/` (gitignored) and exports the public key as `ota_pubkey.h` (committed, embedded into the sketch) |
| `sign_firmware.sh` | AW-006: computes sha256 + RSA-PKCS1v1.5-SHA256 signature for a firmware binary; used both locally and by the release workflow |
| `ota_pubkey.h` | AW-006: generated public-key header (N/E raw bytes), `#include`d by `sketch_gh_ota.ino` |

## AW-006: integrity + signing + rollback

`sketch_gh_ota.ino` now verifies sha256 and an RSA-2048 signature (over the sha256 digest) before installing, gates the install behind a UI/button/serial confirmation, and relies on `arduino-esp32`'s built-in app-rollback hook (`verifyOta()`) for a self-test-triggered rollback. See `docs/ota/10-aw006-integrity-signing-rollback-e2e.md` for the full design + destructive-test results, and `docs.local/operations/ota-e2e-claude-report.md` for the execution log (local-only).

```bash
./gen_keys.sh                              # one-time: dev keypair + ota_pubkey.h
./sign_firmware.sh dist/firmware-vX.Y.Z.bin  # prints sha256=... signature=...
python3 update_manifest.py X.Y.Z <url> <size> ../firmware/manifest.json <sha256> <signature>
```

## Release flow (GitHub Actions)

Tag `vX.Y.Z` (push to main) → `.github/workflows/release.yml`:
build `firmware-vX.Y.Z.bin` → create/update GitHub Release + upload assets → update manifest.json (fallback channel) → devices discover the new version over OTA.

## Local manual build

```bash
# arduino-cli local build (requires arduino-cli + esp32 core installed)
./build_arduino.sh 1.0.0   # → dist/firmware-v1.0.0.bin (with the dual-slot OTA partition table)

# or the Wokwi cloud build API (for simulator verification)
python3 build_gh.py 1.0.0 latest bin/firmware-v1.0.0.bin
```

The chip must match: fqbn defaults to `esp32:esp32:esp32` (the Wokwi simulator is an ESP32 chip; ESP32-S3 requires a different fqbn, and the images are not interchangeable).
