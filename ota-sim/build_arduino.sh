#!/usr/bin/env bash
# build_arduino.sh — 用 arduino-cli 本地编译 OTA 固件（pipeline 与本地通用）
# 用法: ./build_arduino.sh <version> [out_dir]
# 环境: ARDUINO_DATA_DIR 可覆盖 arduino-cli 数据目录（默认 ~/.arduino15）
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

# 渲染带版本号的 sketch 变体（避免 shell 引号地狱）
python3 - "$VERSION" "$HERE" "$SKETCH_DIR" <<'PY'
import sys, pathlib
version, here, sdir = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
s = (here / "sketch_gh_ota.ino").read_text(encoding="utf-8")
old = '#ifndef FW_VERSION\n#define FW_VERSION "1.0.0"\n#endif'
new = f'#ifndef FW_VERSION\n#define FW_VERSION "{version}"\n#endif'
assert old in s, "FW_VERSION block not found"
s = s.replace(old, new)
(sdir / "sketch_gh_ota.ino").write_text(s, encoding="utf-8")
# esp32 core 的 prebuild hook 3：sketch 目录的 partitions.csv 会覆盖默认分区表（OTA 双槽）
(sdir / "partitions.csv").write_text((here / "custom_partitions.csv").read_text(encoding="utf-8"), encoding="utf-8")
PY

arduino-cli compile --fqbn esp32:esp32:esp32 \
  --output-dir "$HERE/$OUT_DIR" "$SKETCH_DIR"

BIN=$(ls "$HERE/$OUT_DIR"/sketch_gh_ota.ino.bin)
cp "$BIN" "$HERE/$OUT_DIR/firmware-v${VERSION}.bin"
SIZE=$(stat -c%s "$HERE/$OUT_DIR/firmware-v${VERSION}.bin")
echo "=== wrote ${SIZE} bytes -> $OUT_DIR/firmware-v${VERSION}.bin (magic 0x$(xxd -p -l1 "$HERE/$OUT_DIR/firmware-v${VERSION}.bin"))"
echo "SIZE=${SIZE}"
