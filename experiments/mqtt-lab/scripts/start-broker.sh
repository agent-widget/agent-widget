#!/usr/bin/env bash
# Start the local lab broker (eclipse-mosquitto container).
#
#  1. generates broker TLS certs if missing (broker/certs/)
#  2. generates broker/state/acl.conf from the template + per-device cohorts
#  3. provisions users in broker/state/passwd:
#       server            -> fixed lab password
#       <deviceId>        -> one RANDOM password per device, stored in
#                            broker/state/device-creds.env (gitignored);
#                            the device sim reads its own secret from there
#  4. starts the container and waits for port 1883
#
# Credentials are LOCAL TEST ONLY. See README before reusing anywhere.
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LAB_ROOT"

SERVER_USER="server"
SERVER_PASS="srv-dev-pass"
IMG="eclipse-mosquitto:2"
STATE_DIR="broker/state"
CREDS="$STATE_DIR/device-creds.env"

# Fleet ids come from the single source of truth (sims/common.py).
FLEET="$(python3 -c "import sys; sys.path.insert(0,'sims'); import common; print(' '.join(common.FLEET))")"
echo ">> fleet: $FLEET"

# 1. TLS certs -------------------------------------------------------------
if [ ! -f broker/certs/broker.crt ]; then
  echo ">> generating local CA + broker TLS certs (8883)"
  broker/scripts/gen-certs.sh
fi

mkdir -p "$STATE_DIR/data" "$STATE_DIR/log"

# 2. per-device cohort ACLs -------------------------------------------------
scripts/gen-acl.sh

# 3. users ------------------------------------------------------------------
PASSWD="$STATE_DIR/passwd"
if [ ! -f "$PASSWD" ]; then
  echo ">> provisioning users (server + one RANDOM password per device)"
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$PWD/$STATE_DIR:/mosquitto/config" "$IMG" \
    mosquitto_passwd -c -b /mosquitto/config/passwd "$SERVER_USER" "$SERVER_PASS"
  : > "$CREDS"
  for dev in $FLEET; do
    # openssl -base64 -A keeps lines short; avoid chars that break passwd files
    dev_pass="$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-24)"
    docker run --rm --user "$(id -u):$(id -g)" \
      -v "$PWD/$STATE_DIR:/mosquitto/config" "$IMG" \
      mosquitto_passwd -b /mosquitto/config/passwd "$dev" "$dev_pass"
    echo "$dev=$dev_pass" >> "$CREDS"
  done
  chmod 600 "$CREDS"
  echo ">> per-device secrets written to $CREDS (gitignored)"
else
  echo ">> passwd file exists ($PASSWD) — keeping existing users"
  [ -f "$CREDS" ] || echo "!! WARNING: $CREDS missing — device sims cannot authenticate"
fi

# 4. start -------------------------------------------------------------------
export MQTT_LAB_UID="$(id -u)" MQTT_LAB_GID="$(id -g)"
docker compose -f broker/docker-compose.yml up -d

echo -n ">> waiting for broker on 1883"
for _ in $(seq 1 30); do
  if nc -z 127.0.0.1 1883 2>/dev/null; then
    echo " OK"
    break
  fi
  echo -n "."
  sleep 1
done

docker compose -f broker/docker-compose.yml ps
echo
echo ">> broker endpoints:"
echo "   MQTT       tcp://127.0.0.1:1883"
echo "   MQTT+TLS   ssl://127.0.0.1:8883   (CA: broker/certs/ca.crt)"
echo "   WebSocket  ws://127.0.0.1:9001"
echo ">> operator: $SERVER_USER / $SERVER_PASS  (local test only)"
echo ">> devices: one random secret per device, see $CREDS"
