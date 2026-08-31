#!/usr/bin/env bash
# One-time setup: create the Python venv and install the lab dependencies.
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LAB_ROOT"

python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet "paho-mqtt>=2.0,<3" "jsonschema>=4"

echo ">> venv ready: $LAB_ROOT/.venv"
echo ">> run the sims as: $LAB_ROOT/.venv/bin/python sims/device.py ..."
