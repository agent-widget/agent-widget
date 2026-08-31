#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "esp_partition.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Verifies an RSA-2048 PKCS#1 v1.5 SHA-256 signature over a 32-byte digest
 * using the embedded trust_store public key. Byte-for-byte compatible with
 * ota-sim/sign_firmware.sh (openssl pkeyutl -sign -pkeyopt digest:sha256):
 * the signature is over the raw digest bytes, not a second hash of them.
 *
 * @return ESP_OK if the signature is valid, ESP_ERR_INVALID_SIZE if sig_len
 *         is not 256, ESP_FAIL if the signature does not verify.
 */
esp_err_t ota_verifier_check_signature(const uint8_t digest[32], const uint8_t *sig, size_t sig_len);

/**
 * Hashes exactly `len` bytes starting at offset 0 of `part` using chunked
 * esp_partition_read() + SHA-256. Never reads past `len` (no hashing of
 * unused 0xff tail bytes).
 */
esp_err_t ota_verifier_sha256_partition(const esp_partition_t *part, size_t len, uint8_t out_digest[32]);

#ifdef __cplusplus
}
#endif
