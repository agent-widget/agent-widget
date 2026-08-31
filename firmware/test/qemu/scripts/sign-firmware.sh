#!/usr/bin/env bash
# sign-firmware.sh — compute sha256 + RSA-PKCS1v1.5-SHA256 signature (over the
# sha256 digest, not the raw bytes) for a firmware binary. Byte-for-byte the
# same convention as ota-sim/sign_firmware.sh (openssl pkeyutl -sign -pkeyopt
# digest:sha256), so ota_verifier.c's mbedtls_rsa_pkcs1_verify() call matches.
#
# Usage: ./sign-firmware.sh <firmware.bin> [priv_key_pem]
# Prints: sha256=<hex>\nsignature=<base64>
set -euo pipefail

BIN="${1:?usage: sign-firmware.sh <firmware.bin> [priv_key_pem]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PRIV="${2:-$HERE/../../../../keys/fw_ota_dev_priv.pem}"

[[ -f "$BIN" ]] || { echo "firmware not found: $BIN" >&2; exit 1; }
[[ -f "$PRIV" ]] || { echo "private key not found: $PRIV (run keys/gen_fw_ota_keys.sh first)" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

SHA256_HEX="$(openssl dgst -sha256 -binary "$BIN" | tee "$TMP/digest.bin" | xxd -p -c 256)"
openssl pkeyutl -sign -inkey "$PRIV" -pkeyopt digest:sha256 -in "$TMP/digest.bin" -out "$TMP/sig.bin"
SIGNATURE_B64="$(base64 -w0 "$TMP/sig.bin")"

echo "sha256=$SHA256_HEX"
echo "signature=$SIGNATURE_B64"
