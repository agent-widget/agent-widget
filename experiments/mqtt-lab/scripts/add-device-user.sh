#!/usr/bin/env bash
# Add a broker user for a new device id (username == deviceId, like prod).
# A random per-device secret is generated (or PRESERVED on re-runs — rerunning
# this script for an existing device is idempotent and does not rotate the
# password unless --rotate is given) and recorded in
# broker/state/device-creds.env; optional extra cohort groups are recorded in
# broker/state/device-extra-groups.conf; then the ACL is regenerated.
#
# Usage: scripts/add-device-user.sh <deviceId> [extra-groups...] [--rotate]
#   extra-groups: additional cohort groups this device may subscribe to,
#                 e.g. `scripts/add-device-user.sh esp32s3-cafebabe beta`
#   --rotate:     generate a new secret even for an existing device
set -euo pipefail
cd "$(dirname "$0")/.."

DEV="${1:-}"
[ -n "$DEV" ] || { echo "usage: $0 <deviceId> [extra-groups...] [--rotate]"; exit 1; }
shift || true

# --- strict identifier validation (config/ACL injection guard) ------------
if ! printf '%s' "$DEV" | grep -qE '^[A-Za-z0-9_-]+$'; then
  echo "error: deviceId '$DEV' must match ^[A-Za-z0-9_-]+\$" >&2
  exit 1
fi

ROTATE=0
EXTRA_GROUPS=""
for a in "$@"; do
  if [ "$a" = "--rotate" ]; then ROTATE=1; continue; fi
  printf '%s' "$a" | grep -qE '^[A-Za-z0-9_-]+$' || { echo "error: group '$a' invalid" >&2; exit 1; }
  EXTRA_GROUPS="$EXTRA_GROUPS $a"
done
EXTRA_GROUPS="${EXTRA_GROUPS# }"

[ -f broker/state/passwd ] || { echo "broker not provisioned yet — run scripts/start-broker.sh first"; exit 1; }

CREDS="broker/state/device-creds.env"
touch "$CREDS"

# 1. secret: reuse the existing one unless --rotate
existing="$(grep "^$DEV=" "$CREDS" | head -1 | cut -d= -f2- || true)"
if [ -n "$existing" ] && [ "$ROTATE" -eq 0 ]; then
  dev_pass="$existing"
  echo ">> device '$DEV' already provisioned — keeping existing secret (use --rotate to change it)"
else
  dev_pass="$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-24)"
  echo ">> generated new secret for '$DEV'"
fi

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/broker/state:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/passwd "$DEV" "$dev_pass"

# 2. record the secret (idempotent: replace an existing line)
grep -v "^$DEV=" "$CREDS" > "$CREDS.tmp" || true
echo "$DEV=$dev_pass" >> "$CREDS.tmp"
mv "$CREDS.tmp" "$CREDS"
chmod 600 "$CREDS"

# 3. record extra cohort groups (idempotent)
if [ -n "$EXTRA_GROUPS" ]; then
  EXTRA_FILE="broker/state/device-extra-groups.conf"
  touch "$EXTRA_FILE"
  grep -v "^$DEV " "$EXTRA_FILE" > "$EXTRA_FILE.tmp" || true
  echo "$DEV $EXTRA_GROUPS" >> "$EXTRA_FILE.tmp"
  mv "$EXTRA_FILE.tmp" "$EXTRA_FILE"
fi

# 4. regenerate the ACL (covers the new device + its cohorts)
scripts/gen-acl.sh

bucket="$(python3 -c "import sys; sys.path.insert(0,'sims'); import common; print(common.canary_bucket('$DEV'))")"
echo ">> provisioned '$DEV' (cohorts: canary-$bucket + stable${EXTRA_GROUPS:+" + $EXTRA_GROUPS"})"
echo ">> restart the broker for changes to take effect: bash scripts/start-broker.sh"
echo ">> run the sim with: .venv/bin/python sims/device.py --device-id $DEV"
