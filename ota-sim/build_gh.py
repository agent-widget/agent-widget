#!/usr/bin/env python3
"""Build the GitHub-OTA simulation firmware for Wokwi with injected version defines.

Usage: python3 build_gh.py <fw_version> <ota_target> <out.bin> [fqbn]

  fw_version     e.g. 1.0.0  — current firmware version (FW_VERSION)
  ota_target     latest | x.y.z — what this build should upgrade to (OTA_TARGET_VERSION)
  out.bin        output path
  fqbn           default esp32:esp32:esp32

Prints the final size on stdout (parse for the manifest).
"""
import sys, json, base64, urllib.request

SKETCH = "sketch_gh_ota.ino"


def build(fw_version, ota_target, out_bin, fqbn="esp32:esp32:esp32"):
    with open(SKETCH, encoding="utf-8") as f:
        sketch = f.read()

    # inject version defines (replace the guarded defaults)
    old_v = '#ifndef FW_VERSION\n#define FW_VERSION "1.0.0"\n#endif'
    new_v = f'#ifndef FW_VERSION\n#define FW_VERSION "{fw_version}"\n#endif'
    old_t = '#ifndef OTA_TARGET_VERSION\n#define OTA_TARGET_VERSION "latest"\n#endif'
    new_t = f'#ifndef OTA_TARGET_VERSION\n#define OTA_TARGET_VERSION "{ota_target}"\n#endif'
    assert old_v in sketch, "FW_VERSION block not found in sketch"
    assert old_t in sketch, "OTA_TARGET_VERSION block not found in sketch"
    sketch = sketch.replace(old_v, new_v).replace(old_t, new_t)

    body = json.dumps({
        "sketch": sketch,
        "files": [],
        "board": fqbn,
        "target": "esp32",
        "options": {"skipCache": False, "symbols": False},
    }).encode()
    req = urllib.request.Request(
        "https://wokwi.com/build", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=300)
    d = json.loads(r.read())
    if d.get("stderr"):
        print("=== build stderr ===")
        print(d["stderr"])
    print("=== build stdout ===")
    print(d.get("stdout", ""))
    raw = base64.b64decode(d["hex"])
    with open(out_bin, "wb") as f:
        f.write(raw)
    print(f"=== wrote {len(raw)} bytes -> {out_bin} (magic 0x{raw[0]:02x})")
    return len(raw)


if __name__ == "__main__":
    fw_version = sys.argv[1]
    ota_target = sys.argv[2]
    out_bin = sys.argv[3]
    fqbn = sys.argv[4] if len(sys.argv) > 4 else "esp32:esp32:esp32"
    size = build(fw_version, ota_target, out_bin, fqbn)
    print(f"SIZE={size}")
