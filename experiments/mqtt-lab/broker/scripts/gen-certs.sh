#!/usr/bin/env bash
# Generate a local test CA + broker certificate for the 8883 TLS listener.
# Output: broker/certs/{ca.key,ca.crt,broker.key,broker.crt,broker.csr}
# Local test only: self-signed, 10-year validity, all artifacts gitignored.
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # -> mqtt-lab/
CERT_DIR="$LAB_ROOT/broker/certs"
mkdir -p "$CERT_DIR"

CA_KEY="$CERT_DIR/ca.key"
CA_CRT="$CERT_DIR/ca.crt"
BROKER_KEY="$CERT_DIR/broker.key"
BROKER_CSR="$CERT_DIR/broker.csr"
BROKER_CRT="$CERT_DIR/broker.crt"
SAN_FILE="$CERT_DIR/broker-san.cnf"

if [ -f "$BROKER_CRT" ]; then
  echo "certs already exist in $CERT_DIR (delete them to regenerate)"
  exit 0
fi

HOSTNAME="$(hostname 2>/dev/null || echo localhost)"

echo ">> generating CA key/cert"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CA_KEY" -out "$CA_CRT" -days 3650 \
  -subj "/CN=aw-mqtt-lab-ca" >/dev/null 2>&1

echo ">> generating broker key/CSR"
openssl req -newkey rsa:2048 -nodes \
  -keyout "$BROKER_KEY" -out "$BROKER_CSR" \
  -subj "/CN=aw-mqtt-broker" >/dev/null 2>&1

cat > "$SAN_FILE" <<EOF
subjectAltName = DNS:localhost, DNS:aw-mqtt-broker, DNS:$HOSTNAME, IP:127.0.0.1, IP:0.0.0.0
EOF

echo ">> signing broker certificate with CA (SAN: localhost/$HOSTNAME)"
openssl x509 -req -in "$BROKER_CSR" \
  -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -out "$BROKER_CRT" -days 3650 \
  -extfile "$SAN_FILE" >/dev/null 2>&1

chmod 600 "$CA_KEY" "$BROKER_KEY"
echo ">> done:"
ls -l "$CERT_DIR"/*.crt "$CERT_DIR"/*.key
echo ">> devices and clients must trust: $CA_CRT"
