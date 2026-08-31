#!/usr/bin/env bash
# build_arduino.sh — 用 arduino-cli 本地编译 OTA 固件（pipeline 与本地通用）
# 用法: ./build_arduino.sh <version> [out_dir]
# 环境: ARDUINO_DATA_DIR 可覆盖 arduino-cli 数据目录（默认 ~/.arduino15）
#       OTA_TARGET_VERSION_OVERRIDE / CHECK_INTERVAL_MS_OVERRIDE / SELFTEST_FORCE_FAIL_OVERRIDE
#       可选，用于产出破坏性测试用的固件变体（不影响正常发布构建）
set -euo pipefail

VERSION="${1:?usage: build_arduino.sh <version> [out_dir]}"
OUT_DIR="${2:-dist}"
HERE="$(cd "$(dirname "$0")" && pwd)"

export ARDUINO_DIRECTORIES_DATA="${ARDUINO_DATA_DIR:-$HOME/.arduino15}"
export ARDUINO_DIRECTORIES_DOWNLOADS="${ARDUINO_DIRECTORIES_DATA}/downloads"

TMP="$HERE/build_tmp"
SKETCH_DIR="$TMP/sketch_gh_ota"
rm -rf "$TMP" "$OUT_DIR"
mkdir -p "$SKETCH_DIR" "$OUT_DIR" "${ARDUINO_DIRECTORIES_DATA}/cache" "${ARDUINO_DIRECTORIES_DATA}/user"

# 自包含 config（数据/缓存目录全在工作区，避免 ~ 目录权限问题）
CONF="$TMP/arduino-cli.yaml"
cat > "$CONF" <<EOF
build_cache:
  path: ${ARDUINO_DIRECTORIES_DATA}/cache
directories:
  data: ${ARDUINO_DIRECTORIES_DATA}
  downloads: ${ARDUINO_DIRECTORIES_DATA}/downloads
  user: ${ARDUINO_DIRECTORIES_DATA}/user
EOF
export ARDUINO_CONFIG_FILE="$CONF"

# 渲染带版本号（及可选测试变体宏）的 sketch（避免 shell 引号地狱）
python3 - "$VERSION" "$HERE" "$SKETCH_DIR" \
  "${OTA_TARGET_VERSION_OVERRIDE:-}" "${CHECK_INTERVAL_MS_OVERRIDE:-}" "${SELFTEST_FORCE_FAIL_OVERRIDE:-}" <<'PY'
import sys, pathlib
version, here, sdir, target_ov, interval_ov, selftest_ov = sys.argv[1:7]
here, sdir = pathlib.Path(here), pathlib.Path(sdir)
s = (here / "sketch_gh_ota.ino").read_text(encoding="utf-8")
old = '#ifndef FW_VERSION\n#define FW_VERSION "1.0.0"\n#endif'
new = f'#ifndef FW_VERSION\n#define FW_VERSION "{version}"\n#endif'
assert old in s, "FW_VERSION block not found"
s = s.replace(old, new)
if target_ov:
    old_t = '#ifndef OTA_TARGET_VERSION\n#define OTA_TARGET_VERSION "latest"\n#endif'
    new_t = f'#ifndef OTA_TARGET_VERSION\n#define OTA_TARGET_VERSION "{target_ov}"\n#endif'
    assert old_t in s, "OTA_TARGET_VERSION block not found"
    s = s.replace(old_t, new_t)
if interval_ov:
    old_i = '#ifndef CHECK_INTERVAL_MS\n#define CHECK_INTERVAL_MS 3600000UL\n#endif'
    new_i = f'#ifndef CHECK_INTERVAL_MS\n#define CHECK_INTERVAL_MS {interval_ov}UL\n#endif'
    assert old_i in s, "CHECK_INTERVAL_MS block not found"
    s = s.replace(old_i, new_i)
if selftest_ov:
    old_f = '#ifndef SELFTEST_FORCE_FAIL\n#define SELFTEST_FORCE_FAIL 0\n#endif'
    new_f = f'#ifndef SELFTEST_FORCE_FAIL\n#define SELFTEST_FORCE_FAIL {selftest_ov}\n#endif'
    assert old_f in s, "SELFTEST_FORCE_FAIL block not found"
    s = s.replace(old_f, new_f)
(sdir / "sketch_gh_ota.ino").write_text(s, encoding="utf-8")
# esp32 core 的 prebuild hook 3：sketch 目录的 partitions.csv 会覆盖默认分区表（OTA 双槽）
(sdir / "partitions.csv").write_text((here / "custom_partitions.csv").read_text(encoding="utf-8"), encoding="utf-8")
# 多文件 sketch：ota_pubkey.h 与 .ino 同目录，arduino-cli 会自动纳入编译
(sdir / "ota_pubkey.h").write_text((here / "ota_pubkey.h").read_text(encoding="utf-8"), encoding="utf-8")
PY

arduino-cli lib install "TFT_eSPI" >/dev/null 2>&1 || echo "(TFT_eSPI already installed or install skipped)"

arduino-cli compile --fqbn esp32:esp32:esp32 \
  --output-dir "$HERE/$OUT_DIR" "$SKETCH_DIR"

BIN=$(ls "$HERE/$OUT_DIR"/sketch_gh_ota.ino.bin)
cp "$BIN" "$HERE/$OUT_DIR/firmware-v${VERSION}.bin"
SIZE=$(stat -c%s "$HERE/$OUT_DIR/firmware-v${VERSION}.bin")
echo "=== wrote ${SIZE} bytes -> $OUT_DIR/firmware-v${VERSION}.bin (magic 0x$(xxd -p -l1 "$HERE/$OUT_DIR/firmware-v${VERSION}.bin"))"
echo "SIZE=${SIZE}"
