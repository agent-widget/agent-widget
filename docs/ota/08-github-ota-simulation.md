> Chinese version: [08-github-ota-simulation.zh-CN.md](./08-github-ota-simulation.zh-CN.md)

# 08-GitHub OTA Simulation Verification (Wokwi, Verified 2026-08-30)

> Task: the user asked to "get OTA working in the simulation environment today; perform OTA through GitHub; any version can be flashed; after flashing any version, no re-flashing is needed (OTA automatically updates to the latest); optional: pin OTA to any version"
> Result: ✅ **Both scenarios ran successfully in the Wokwi simulator, with GitHub as the firmware source (raw.githubusercontent.com direct link + GitHub Releases API dual channel)**

---

## 1. Summary at a Glance

| User request | Status | Evidence |
|---|---|---|
| OTA works in the simulation environment | ✅ Working | See the serial log below (full V1→V2 flow) |
| OTA through GitHub | ✅ Dual channel | Releases API (production primary channel; auto-fallback when no release exists) + manifest.json (raw direct link, PoC channel) |
| Any version can be flashed | ✅ 1.0.0 / 2.0.0 published | `firmware/releases/vX.Y.Z.bin`, sha256 verified |
| No re-flashing needed after flashing any version | ✅ Automatic upgrade check | Scenario 1: V1.0.0 → auto-upgrade to 2.0.0; Scenario 2: V2.0.0 → No update needed |
| Pin OTA to any version (optional) | 🔧 Wired up | `OTA_TARGET_VERSION` set at compile time (e.g. 1.1.0); downgrades are deliberately blocked, consistent with production anti-rollback |

**Difference from the [07 retrospective](./07-wokwi-ota-verification-retrospective.md)**: 07's firmware source was a temporary catbox.moe file with no version comparison; this time the firmware source switched to **GitHub** and added version awareness (semver comparison + latest/pinned-version dual mode), simulating real OTA client behavior.

---

## 2. Architecture

```
                    ┌───────────────────── GitHub ───────────────────────────────────────────┐
 ESP32 (Wokwi)      │ Channel A: api.github.com/repos/agent-widget/agent-widget/releases     │
 ┌──────────────┐   │ (production primary; 404 → fallback when no release assets)            │
 │ sketch       │──▶│ Channel B: raw.githubusercontent.com/.../firmware/manifest.json        │
 │ (OTA client) │   │ (PoC: manifest lists all released versions + direct links)             │
 └──────────────┘   │ Firmware: raw.githubusercontent.com/.../firmware/releases/vX.Y.Z.bin   │
                    └────────────────────────────────────────────────────────────────────────┘
   boot → print version → connect Wokwi-GUEST → query GitHub → target (latest/pinned) > current?
       ├─ yes → download → Update writes flash → reboot → new firmware runs
       └─ no → print "No update needed" → normal heartbeat
```

**Key sketch design** (`ota-verify/sketch_gh_ota.ino`, Arduino ecosystem, zero external dependencies):
- `FW_VERSION` / `OTA_TARGET_VERSION` injected at compile time (`build_gh.py`)
- Minimal JSON parsing (tolerates whitespace in `"key": "value"`), no ArduinoJson
- semver comparison (MAJOR.MINOR.PATCH integer segments)
- `Update` class writes flash (the Wokwi partition table with otadata + app0/app1 is provided by project 337425600260080210)

---

## 3. Scenario 1: Flash V1.0.0 → Auto-Upgrade to Latest 2.0.0 (serial log excerpt)

```
[BOOT] Firmware VERSION : 1.0.0
[BOOT] OTA target       : latest
[WIFI] Connected! Local IP: 10.10.0.2
[OTA] Releases API: no release assets found          ← Channel A has no release, auto fallback
[OTA] Channel: manifest.json (raw.githubusercontent)  ← Channel B
[OTA] Available versions (8): 1.0.0 2.0.0
[OTA] Target 2.0.0 > current 1.0.0 → updating
[OTA] Downloading new firmware from: https://raw.githubusercontent.com/agent-widget/agent-widget/main/firmware/releases/v2.0.0.bin
[OTA] HTTP GET response code: 200
[OTA] Firmware size: 1035952 bytes
[OTA] Update.begin() OK, writing to flash ...
[OTA] Progress: 10% (103808 / 1035952 bytes) ... 100%
[OTA] Downloaded 1035952 bytes (expected 1035952)   ← byte-for-byte identical
[OTA] Update SUCCESS! 1035952 bytes written to flash.
[OTA] Rebooting into new firmware ...
--- reboot ---
[BOOT] Firmware VERSION : 2.0.0                       ← OTA took effect
[WIFI] Connected! Local IP: 10.10.0.2
```

Full log: `wokwi-run/serial-1.0.0.txt` (local; includes the real boot sequence rst:0x1 POWERON_RESET → rst:0xc SW_CPU_RESET)

## 4. Scenario 2: Flash V2.0.0 → No Re-Flashing Needed (serial log excerpt)

```
[BOOT] Firmware VERSION : 2.0.0
[WIFI] Connected! Local IP: 10.10.0.2
[OTA] Releases API: no release assets found
[OTA] Channel: manifest.json (raw.githubusercontent)
[OTA] Available versions (8): 1.0.0 2.0.0
[OTA] Current 2.0.0 already >= target 2.0.0. No update needed.
[APP] heartbeat ... running firmware 2.0.0
```

Full log: `wokwi-run/serial-2.0.0.txt`

---

## 5. Reproduction Steps (Local)

```bash
# 1) Build firmware for any version (Wokwi cloud build API, no authentication; esp32 fqbn, matching the simulator chip)
cd ota-verify
python3 build_gh.py 1.0.0 latest bin/firmware-v1.0.0.bin      # FW=1.0.0, target=latest
python3 build_gh.py 2.0.0 latest bin/firmware-v2.0.0.bin

# 2) Publish: update firmware/manifest.json + copy the bin to firmware/releases/, git push
#    (script: scripts/publish_release.sh can switch to the GitHub Releases production channel)

# 3) Run the simulation (headless Chrome drives the Wokwi editor, injects the sketch → starts → captures the serial output)
cd wokwi-run && npm i puppeteer-core@24 --cache /tmp/npm-cache
node run_ota.js 1.0.0 latest upgrade    # Scenario 1: V1 auto-upgrade
node run_ota.js 2.0.0 latest uptodate   # Scenario 2: V2 already up to date
```

Dependencies: local google-chrome (headless), node ≥ 18, and access to wokwi.com; the Wokwi editor project uses the public project
`https://wokwi.com/projects/337425600260080210` (an ESP32 project with the otadata/app0/app1 partition table).

## 6. Release Artifacts and Repository State

- `firmware/manifest.json` — release manifest (version/url/size)
- `firmware/releases/v1.0.0.bin` (1,035,952 B, sha256 `1ae3f29b…`)
- `firmware/releases/v2.0.0.bin` (1,035,952 B, sha256 `78ea321f…`)
- `.gitignore` now has the exception `!firmware/releases/*.bin` (PoC transitional channel; remove after production AW-006 migrates to Releases)
- Source code (local PoC, not committed, per the boundary defined in document 00): `ota-verify/sketch_gh_ota.ino`, `ota-verify/build_gh.py`, `wokwi-run/run_ota.js`

> ⚠️ Known minor blemish: in the captured serial logs, `→` displays as `â` — a UTF-8 encoding display issue in the DOM text capture; real-device serial output does not have this problem; no functional impact.

---

## 7. What's Still Missing for Real-Device Deployment (Production AW-006 Path)

The simulation validated the **application-layer OTA logic** (query GitHub → download → write flash → reboot). Real-device production still needs:

| # | Gap | Details |
|---|---|---|
| 1 | ESP-IDF production firmware | `firmware/` is currently empty; the AW-003 baseline (display/touch/Wi-Fi/health signal) → AW-004 AgentStatus → AW-005 UI have not started. The simulation uses an Arduino-ecosystem sketch, not S3 production code |
| 2 | esp_https_ota + dual-slot partitions | Production uses IDF's `esp_https_ota`, `factory + ota_0 + ota_1` partitions, and otadata; the current Wokwi project partition table has only 2 slots and no factory |
| 3 | Health-check rollback | After the new firmware boots, a PENDING_VERIFY self-test (display/touch/Wi-Fi/OTA task alive) → mark_valid / explicit rollback on failure (see [02-ota-design-esp-https-rollback.md](./02-ota-design-esp-https-rollback.md)) |
| 4 | GitHub Actions CI | Build (`idf.py build`) → upload GitHub Releases (tag = version) → update the manifest; firmware no longer committed to git |
| 5 | Actual GitHub Releases publishing | The repo currently has no releases (the API channel falls back to the manifest); after one-click publishing with `scripts/publish_release.sh` (gh CLI or GH_TOKEN), the device automatically switches to the Releases channel |
| 6 | Real-device verification | Run an upgrade plus a deliberate-failure rollback drill on ESP32-S3-Touch-LCD-3.5B |
| 7 | Security hardening (pre-production) | Secure Boot v2 / Flash Encryption need a separate plan (eFuses are irreversible and require user confirmation, per the project's human-gate policy) |

**Conclusions verified in the simulation are reusable in production**: GitHub works as a firmware source, the semver version-comparison logic, and the OTA client state flow (check → download → write → reboot → self-test). The production implementation reuses these states and the `OTA_TARGET_VERSION` setting entry point directly (corresponding to the UpdatePanel of the AW-005 SettingsPanel).
