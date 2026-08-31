#!/usr/bin/env bash
# Start the local lab broker (eclipse-mosquitto container).
#
#  1. generates broker TLS certs if missing (broker/certs/)
#  2. provisions users in broker/state/passwd (server + one user per fleet
#     device; username == deviceId, mirroring per-device credentials)
#  3. starts the container and waits for port 1883
#
# Credentials below are LOCAL TEST ONLY. See README before reusing anywhere.
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$LAB_ROOT"

SERVER_USER="server"
SERVER_PASS="srv-dev-pass"
DEVICE_PASS="dev-test-pass"
IMG="eclipse-mosquitto:2"
STATE_DIR="broker/state"

# Fleet ids come from the single source of truth (sims/common.py).
FLEET="$(python3 -c "import sys; sys.path.insert(0,'sims'); import common; print(' '.join(common.FLEET))")"

echo ">> fleet: $FLEET"

# 1. TLS certs -------------------------------------------------------------
if [ ! -f broker/certs/broker.crt ]; then
  echo ">> generating local CA + broker TLS certs (8883)"
  broker/scripts/gen-certs.sh
fi

mkdir -p "$STATE_DIR/data" "$STATE_DIR/log"

# 2. users -----------------------------------------------------------------
PASSWD="$STATE_DIR/passwd"
if [ ! -f "$PASSWD" ]; then
  echo ">> provisioning users (server + one per device)"
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$PWD/$STATE_DIR:/mosquitto/config" "$IMG" \
    mosquitto_passwd -c -b /mosquitto/config/passwd "$SERVER_USER" "$SERVER_PASS"
  for dev in $FLEET; do
    docker run --rm --user "$(id -u):$(id -g)" \
      -v "$PWD/$STATE_DIR:/mosquitto/config" "$IMG" \
      mosquitto_passwd -b /mosquitto/config/passwd "$dev" "$DEVICE_PASS"
  done
else
  echo ">> passwd file exists ($PASSWD) — keeping existing users"
fi

# 3. start ------------------------------------------------------------------
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
echo ">> users: server / $SERVER_USER:$SERVER_PASS"
echo "          device per id / <deviceId>:$DEVICE_PASS"
