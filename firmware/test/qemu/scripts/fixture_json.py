#!/usr/bin/env python3
"""fixture_json.py — writes the small JSON fixtures the QEMU scenarios serve.

  fixture_json.py manifest --out DIR/manifest.json --version V --url U \
      --size N --sha256 H --signature B64 [--min-version V]
      [repeat --version/--url/... groups are not supported; call multiple
       times with --append to build a multi-record manifest]

  fixture_json.py latest --out DIR/api/releases/latest --version V
"""
import argparse
import json
import os
import sys


def cmd_manifest(args):
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    doc = {"releases": []}
    if args.append and os.path.exists(args.out):
        with open(args.out) as f:
            doc = json.load(f)
    doc["releases"].append({
        "schema_version": 1,
        "version": args.version,
        "url": args.url,
        "size": args.size,
        "sha256": args.sha256,
        "signature": args.signature,
        "min_version": args.min_version,
    })
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"wrote {args.out} ({len(doc['releases'])} record(s))")


def cmd_latest(args):
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"tag_name": f"v{args.version}", "assets": []}, f, indent=2)
    print(f"wrote {args.out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest")
    m.add_argument("--out", required=True)
    m.add_argument("--version", required=True)
    m.add_argument("--url", required=True)
    m.add_argument("--size", type=int, required=True)
    m.add_argument("--sha256", required=True)
    m.add_argument("--signature", required=True)
    m.add_argument("--min-version", default="0.0.0")
    m.add_argument("--append", action="store_true")
    m.set_defaults(func=cmd_manifest)

    l = sub.add_parser("latest")
    l.add_argument("--out", required=True)
    l.add_argument("--version", required=True)
    l.set_defaults(func=cmd_latest)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
