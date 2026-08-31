#!/usr/bin/env bash
# Add a broker user for a new device id (username == deviceId, like prod).
# Usage: scripts/add-device-user.sh esp32s3-cafebabe
set -euo pipefail
cd "$(dirname "$0")/.."
DEV="$1"
[ -n "$DEV" ] || { echo "usage: $0 <deviceId>"; exit 1; }
[ -f broker/state/passwd ] || { echo "broker not provisioned yet — run scripts/start-broker.sh first"; exit 1; }
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/broker/state:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/passwd "$DEV" "dev-test-pass"
echo ">> added user '$DEV' (password: dev-test-pass, local test only)"
echo ">> the device sim must run with --device-id $DEV"
