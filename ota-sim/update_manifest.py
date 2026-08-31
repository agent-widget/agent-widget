#!/usr/bin/env python3
"""Add or update one release entry in firmware/manifest.json.

Usage: update_manifest.py <version> <url> <size> <manifest_path> [sha256] [signature_b64]

sha256/signature are optional (AW-006): when present they carry the integrity
metadata for this version regardless of which channel (Releases API vs this
manifest) actually serves the binary bytes — see docs.local/operations
report / docs/ota for why. Pass the literal string "-" to omit either field
explicitly while still supplying the other.

Keeps entries sorted by semver descending, preserves existing entries.
"""
import json
import sys


def ver_key(v: str):
    parts = []
    for seg in v.split("."):
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        try:
            parts.append(int(digits))
        except ValueError:
            parts.append(0)
    return parts


def main():
    version, url, size, path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    sha256 = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] != "-" else None
    signature = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] != "-" else None

    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    entries = [r for r in doc.get("releases", []) if r.get("version") != version]
    entry = {"version": version, "url": url, "size": size}
    if sha256:
        entry["sha256"] = sha256
    if signature:
        entry["signature"] = signature
    entries.append(entry)
    entries.sort(key=lambda r: ver_key(r["version"]), reverse=True)
    doc["releases"] = entries

    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"manifest updated: {[r['version'] for r in entries]}")


if __name__ == "__main__":
    main()
