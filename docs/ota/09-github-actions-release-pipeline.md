> Chinese version: [09-github-actions-release-pipeline.zh-CN.md](./09-github-actions-release-pipeline.zh-CN.md)

# 09-GitHub Actions Release Pipeline (Configured)

> Date: 2026-08-30
> Status: ✅ Pushed and **verified** (run #33344266887 success, 2026-08-30): pushing tag v2.0.0 → Actions auto-builds (arduino-cli) → creates a Release + uploads firmware-v2.0.0.bin (1,026,560 B, magic 0xE9) → manifest auto-updated. The device simulation side has confirmed the OTA upgrade (V1.0.0 → V2.0.0) completed through the GitHub Releases API channel.

---

## 1. What Was Done

Turned "publishing firmware" from a manual step into an automated one. The flow:

```
push tag vX.Y.Z (main)  ──▶  GitHub Actions
                             ├─ 1. parse the version (v2.0.0 → 2.0.0)
                             ├─ 2. build: ota-sim/build_arduino.sh (local arduino-cli build, esp32 core 3.x + custom OTA dual-slot partition table)
                             ├─ 3. create a GitHub Release + upload firmware-vX.Y.Z.bin
                             └─ 4. update firmware/manifest.json (fallback channel, committed back to main)
device side: boot → GitHub Releases API discovers the new version → automatic OTA upgrade
```

## 2. New Files

| File | Purpose |
|---|---|
| `.github/workflows/release.yml` | Trigger: push tag `v*` or manual workflow_dispatch; uses GITHUB_TOKEN (no user credentials needed) |
| `ota-sim/sketch_gh_ota.ino` | Version-aware OTA client source (Arduino PoC, committed for CI builds) |
| `ota-sim/build_arduino.sh` | Local arduino-cli build (esp32 core 3.x + OTA dual-slot partition table; `./build_arduino.sh <ver>`) |
| `ota-sim/custom_partitions.csv` | OTA partition table (nvs/otadata/app0/app1/spiffs) |
| `ota-sim/build_gh.py` | (standby) Wokwi cloud build script |
| `ota-sim/update_manifest.py` | Updates manifest.json (add/sort/replace entries) |
| `ota-sim/README.md` | Usage instructions |

## 3. How to Use

```bash
# Release v3.0.0 (assuming the code is already on main):
git tag v3.0.0 && git push origin v3.0.0
# → Actions auto-builds + publishes; the device discovers the upgrade automatically on next boot
```

Manual trigger (GitHub Web: Actions → Release firmware → Run workflow, fill in the version; **the tag must already exist**).

## 4. Boundaries and Next Steps (AW-006)

- The current build is an **Arduino PoC** (arduino-cli compiles the app image + OTA dual-slot partition table, the same path used by the simulator/Wokwi). Production replacement point: swap the workflow's build step for ESP-IDF `idf.py build`; the rest of the release/manifest logic stays unchanged.
- Flashing a real device requires a matching partition table (the simulator is controlled by the project's partitions.csv; the ESP-IDF stage is controlled by the sdkconfig partition table).
- The repo's `firmware/releases/*.bin` (raw direct links) and the manifest are retained as the fallback channel; once a Release is published, the device prefers the Releases API. Delete the raw channel and the `.gitignore` exception in production.
- Actions run status can be viewed on the repository's Actions page; release results are publicly queryable (`GET /repos/agent-widget/agent-widget/releases`).

## 5. Verification Results (Executed 2026-08-30)

✅ Pushed tag v2.0.0 → run #33344266887 **success**:
1. Actions built the firmware (arduino-cli, with the OTA dual-slot partition table)
2. Release v2.0.0 published, asset firmware-v2.0.0.bin (1,026,560 B, magic 0xE9, sha256 3e3eadc1…)
3. manifest.json auto-updated (releases list: 2.0.0, 1.0.0, URLs pointing to the Release downloads)
4. The Wokwi simulation side confirmed `[OTA] Channel: GitHub Releases API` → downloaded the Release asset → Update SUCCESS → rebooted to V2.0.0 → `No update needed` (simulated serial evidence: `wokwi-run/serial-1.0.0.txt`)

> Root cause of the first failed trigger: the Wokwi cloud build API was unreachable from GitHub runner IPs → switched to local arduino-cli builds (self-contained).
