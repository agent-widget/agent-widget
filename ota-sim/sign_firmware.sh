#!/usr/bin/env bash
# sign_firmware.sh — compute sha256 + RSA-PKCS1v1.5-SHA256 signature (over the
# sha256 digest, not the raw bytes) for a firmware binary, using the dev/CI
# private key. Prints "sha256=<hex> signature=<base64>" on stdout (also usable
# as shell eval'able KEY=VALUE lines for scripting).
#
# Usage: ./sign_firmware.sh <firmware.bin> [priv_key_pem]
set -euo pipefail

BIN="${1:?usage: sign_firmware.sh <firmware.bin> [priv_key_pem]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PRIV="${2:-$HERE/keys/ota_dev_priv.pem}"

[[ -f "$BIN" ]] || { echo "firmware not found: $BIN" >&2; exit 1; }
[[ -f "$PRIV" ]] || { echo "private key not found: $PRIV (run ./gen_keys.sh first)" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

SHA256_HEX="$(openssl dgst -sha256 -binary "$BIN" | tee "$TMP/digest.bin" | xxd -p -c 256)"
# sign the raw 32-byte digest directly (PKCS#1 v1.5, SHA-256 DigestInfo prefix
# added by openssl) — this is what mbedtls_rsa_pkcs1_verify(md_alg=SHA256, hash=..)
# expects on the device side.
openssl pkeyutl -sign -inkey "$PRIV" -pkeyopt digest:sha256 -in "$TMP/digest.bin" -out "$TMP/sig.bin"
SIGNATURE_B64="$(base64 -w0 "$TMP/sig.bin")"

echo "sha256=$SHA256_HEX"
echo "signature=$SIGNATURE_B64"
