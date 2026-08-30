#!/usr/bin/env python3
"""Add or update one release entry in firmware/manifest.json.

Usage: update_manifest.py <version> <url> <size> <manifest_path>

Keeps entries sorted by semver descending, preserves existing entries.
"""
import json
import sys


def ver_key(v: str):
    parts = []
    for seg in v.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return parts


def main():
    version, url, size, path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    entries = [r for r in doc.get("releases", []) if r.get("version") != version]
    entries.append({"version": version, "url": url, "size": size})
    entries.sort(key=lambda r: ver_key(r["version"]), reverse=True)
    doc["releases"] = entries

    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"manifest updated: {[r['version'] for r in entries]}")


if __name__ == "__main__":
    main()
