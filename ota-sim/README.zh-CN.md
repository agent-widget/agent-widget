# ota-sim — 模拟期 GitHub OTA 源（Arduino PoC）

> 本目录是「GitHub OTA 模拟验证」（docs/ota/08）的可复现源，供 GitHub Actions release pipeline 构建。
> **边界**：Arduino 生态 PoC，不是 ESP32-S3 生产固件。生产 AW-006 落地（ESP-IDF + esp_https_ota）后本目录删除。

## 文件

| 文件 | 说明 |
|---|---|
| `sketch_gh_ota.ino` | 版本感知 OTA 客户端（FW_VERSION / OTA_TARGET_VERSION 编译时注入；GitHub Releases API 主通道 + manifest.json 回退） |
| `build_arduino.sh` | arduino-cli 本地编译（esp32 core 3.x + 自定义 OTA 双槽分区表；`./build_arduino.sh <ver> [out_dir]`） |
| `custom_partitions.csv` | OTA 分区表（nvs/otadata/app0/app1/spiffs，与 Wokwi 模拟器一致） |
| `build_gh.py` | （备用）调 Wokwi 云构建 API 编译，模拟器验证用 |
| `update_manifest.py` | 更新 `firmware/manifest.json`（`python3 update_manifest.py <ver> <url> <size> <path> [sha256] [signature_b64]`） |
| `gen_keys.sh` | AW-006：生成（或复用）本地 RSA-2048 签名密钥对（`keys/`，已 gitignore），导出公钥为 `ota_pubkey.h`（入 git，供 sketch 内置） |
| `sign_firmware.sh` | AW-006：计算固件 sha256 + RSA-PKCS1v1.5-SHA256 签名；本地和 release 流水线共用 |
| `ota_pubkey.h` | AW-006：生成的公钥头文件（N/E 原始字节），被 `sketch_gh_ota.ino` `#include` |

## AW-006：完整性 + 签名 + 回滚

`sketch_gh_ota.ino` 现在会在安装前校验 sha256 与 RSA-2048 签名（对 sha256 摘要签名），安装动作被 UI/按键/串口确认门控，回滚依赖 `arduino-esp32` 内置的 app-rollback hook（`verifyOta()`）触发自检失败回滚。完整设计与破坏性测试结果见 `docs/ota/10-aw006-integrity-signing-rollback-e2e.md`；执行过程记录见 `docs.local/operations/ota-e2e-claude-report.md`（仅本地）。

```bash
./gen_keys.sh                                # 一次性：生成密钥对 + ota_pubkey.h
./sign_firmware.sh dist/firmware-vX.Y.Z.bin    # 输出 sha256=... signature=...
python3 update_manifest.py X.Y.Z <url> <size> ../firmware/manifest.json <sha256> <signature>
```

## 发布流程（GitHub Actions）

打 tag `vX.Y.Z`（推送到 main）→ `.github/workflows/release.yml`：
构建 `firmware-vX.Y.Z.bin` → 创建/更新 GitHub Release + 上传资产 → 更新 manifest.json（回退通道）→ 设备 OTA 自动发现新版本。

## 本地手动构建

```bash
# arduino-cli 本地编译（需先安装 arduino-cli + esp32 core）
./build_arduino.sh 1.0.0   # → dist/firmware-v1.0.0.bin（含 OTA 双槽分区表）

# 或 Wokwi 云构建 API（模拟器验证用）
python3 build_gh.py 1.0.0 latest bin/firmware-v1.0.0.bin
```

芯片必须一致：fqbn 默认 `esp32:esp32:esp32`（Wokwi 模拟器为 ESP32 芯片；ESP32-S3 需换 fqbn，且不可互刷）。
