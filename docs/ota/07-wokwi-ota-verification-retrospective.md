> Chinese version: [07-wokwi-ota-verification-retrospective.zh-CN.md](./07-wokwi-ota-verification-retrospective.zh-CN.md)

# 07-Wokwi OTA Simulation Verification Retrospective

> Date: 2026-08-23
> Task: choose the Wokwi solution (the first option from the 06 research), have a higher-capability sub-agent (deepseek-v4-pro) implement Wokwi OTA simulation verification + self-check
> Result: ✅ Full flow verified (10/10 check items), evidence in ota-verify/evidence/serial-log-ota-success.md

---

## 1. Task Review

- **Goal**: run the complete ESP32 OTA flow on the Wokwi simulator (download → write flash → reboot → new firmware runs) as pre-hardware simulation verification
- **Deliverables**: ① reproducible project files (diagram.json / sketch.ino / sketch_v2.ino / partitions.csv / wokwi_build.py) ② real run evidence (serial log) ③ self-check checklist
- **Execution**: higher-capability sub-agent (deepseek-v4-pro, delegation.model upgraded from deepseek-chat) → timeout → main agent took over, fixed, and finished

## 2. Execution Process (including pitfalls)

### Stage 1: sub-agent (deepseek-v4-pro, 600s timeout)
- ✅ Researched the official Wokwi OTA example (389801812438455297) + WiFi ota test (387266104488294401)
- ✅ Discovered the Wokwi cloud build API (POST /build, no auth needed) → wrote wokwi_build.py
- ✅ Compiled V1 firmware (v1.bin, 1,030,992 B, ESP32 chip)
- ⚠️ Error: V2 compiled with the esp32s3 fqbn (chip mismatch causes OTA failure) + catbox upload timeout
- ⏰ Timeout cause: stuck on catbox upload (600s limit)

### Stage 2: main agent took over and fixed
| Problem | Fix |
|---|---|
| V1/V2 chip mismatch | Recompiled V2 with the esp32 fqbn (v2.bin, 889,056 B) |
| catbox upload incomplete | Re-uploaded v2.bin → `https://files.catbox.moe/g8dvdy.bin`, verified byte-identical download |
| sketch.ino URL pointed to the wrong file (pointed to v1) | Updated to g8dvdy.bin, recompiled v1.bin |
| Wokwi web Monaco injection escaping broke the code | Injected base64 in 4 chunks via window → atob decode → setValue (avoiding JS string escaping) |
| vfs out of sync with the Monaco view | Triggered the Monaco save action + operated on a saved project (partition-list) |

### Stage 3: key breakthrough — the partition table
- ❌ Official OTA example run: `Update.begin() FAILED: Partition Could Not be Found`
- 🔍 Root cause: the official example **had no partitions.csv** (the Arduino default partition table has app0 of only 0x140000, and the Wokwi simulator flash layout contains no valid otadata)
- ✅ Found the official Wokwi partition-list project (337425600260080210) with **partitions.csv** (otadata + app0/app1 at 0x1E0000 each)
- ✅ Injected our sketch into that project and reused its partitions.csv → **OTA fully succeeded**

## 3. Verification Results (10/10 PASS)

| # | Check item | Result |
|---|---|---|
| 1 | Real boot flow | ✅ `rst:0x1, boot:0x13, entry 0x400805dc` |
| 2 | V1 firmware runs | ✅ VERSION 1.0.0 |
| 3 | WiFi connected | ✅ Local IP 10.10.0.2 |
| 4 | HTTP download | ✅ GET 200, 889,056 B |
| 5 | Update writes flash | ✅ begin OK, 10%→100% |
| 6 | Firmware integrity | ✅ Downloaded 889056 (expected 889056) |
| 7 | Automatic reboot | ✅ rst:0xc (SW_CPU_RESET) |
| 8 | V2 runs | ✅ VERSION 2.0.0 |
| 9 | **Boots from the OTA partition** | ✅ `Running from partition: app1` |
| 10 | V2 keeps running | ✅ heartbeat |

## 4. Key Lessons (valuable for later projects)

1. **Wokwi's ESP32 simulator supports full OTA semantics** (otadata switching + booting from ota_1) — usable for simulating OTA logic
2. **Wokwi custom partition table**: adding `partitions.csv` (ESP-IDF format) to the project takes effect immediately; the official OTA example failed because it had none
3. **Wokwi cloud build API** (POST wokwi.com/build) compiles firmware without authentication — reusable in local CI
4. **Wokwi web anonymous-project limitations**: Monaco injection can change the view but the vfs stays out of sync (Save requires login) → operating on **already-saved public projects** bypasses this (their vfs is initialized)
5. **Monaco injection of large code**: JS string escaping breaks the code → base64 chunked injection is the most reliable
6. **sub-agent timeout handling**: a timeout doesn't mean failure; check the live transcript + artifact directory, usually most of the work is done
7. **Firmware chip consistency**: the OTA target firmware must be for the same chip as the current firmware (bins compiled for esp32 vs esp32s3 cannot be cross-flashed)

## 5. Deliverables List

```
/mnt/sdc1/Playground/esp32-wokwi-ota/
├── sketch.ino          # V1 firmware (OTA client)
├── sketch_v2.ino       # V2 firmware (upgrade target, prints partition name)
├── diagram.json        # Wokwi circuit diagram
├── partitions.csv      # custom partition table (with OTA slots) ★ key
├── wokwi_build.py      # Wokwi cloud build script (no auth)
├── wokwi_build_retry.py# build script with retry
├── v1.bin / v2.bin     # build artifacts
└── evidence/
    └── serial-log-ota-success.md  # full log + self-check checklist
```

## 6. Follow-up Recommendations

1. **Connect to GitHub Releases**: upload v2.bin to the agent-widget repo's Releases (repo purpose = firmware distribution), the device pulls from GitHub Releases — corresponds to the SafeGithubOTA solution
2. **Rollback verification**: continue on Wokwi to verify "V2 intentionally written broken → rollback to V1" (requires adding failure self-check logic to the sketch)
3. **Real-device porting**: PlatformIO + ESP-IDF project, using the partitions.csv layout verified here for the partition table (extend to the 16MB version per the 02 design)
4. **GitHub Actions**: configure a pipeline to automatically compile firmware (wokwi build API or arduino-cli) → publish to Releases

## References

- [06-ota-simulation-options.md](./06-ota-simulation-options.md) | Wokwi solution research
- [Wokwi partition-list example](https://wokwi.com/projects/337425600260080210) | partitions.csv reference
- [Wokwi OTA example](https://wokwi.com/projects/389801812438455297) | without partition table (failure control)
- Evidence: `ota-verify/evidence/serial-log-ota-success.md`
