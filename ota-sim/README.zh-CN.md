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
| `update_manifest.py` | 更新 `firmware/manifest.json`（`python3 update_manifest.py <ver> <url> <size> <path>`） |

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
