#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define OTA_MANIFEST_MAX_VERSION_LEN 32
#define OTA_MANIFEST_MAX_URL_LEN 256
#define OTA_MANIFEST_SIGNATURE_LEN 256 /* RSA-2048 raw signature bytes */

typedef struct {
    char version[OTA_MANIFEST_MAX_VERSION_LEN];
    char url[OTA_MANIFEST_MAX_URL_LEN];
    uint32_t size;
    uint8_t sha256[32];
    uint8_t signature[OTA_MANIFEST_SIGNATURE_LEN];
    size_t signature_len;
    char min_version[OTA_MANIFEST_MAX_VERSION_LEN];
} ota_manifest_record_t;

/**
 * Parses a manifest document shaped like {"releases": [ {record}, ... ]}.
 * Each record is normalized per codex-architecture.md section 4.1. Records
 * that are missing fields, have the wrong types, or fail length/encoding
 * checks are skipped (logged, not fatal) so one bad entry cannot deny
 * service to the rest of the list.
 */
esp_err_t ota_manifest_parse(const char *json, size_t len,
                              ota_manifest_record_t *out_records, size_t max_records,
                              size_t *out_count);

/** Finds the record matching `version` exactly (semver equality). */
const ota_manifest_record_t *ota_manifest_find(const ota_manifest_record_t *records, size_t count,
                                                const char *version);

/** true if a > b on the numeric major.minor.patch triple (suffix ignored). */
bool ota_manifest_version_gt(const char *a, const char *b);

/** true if a >= b on the numeric major.minor.patch triple. */
bool ota_manifest_version_ge(const char *a, const char *b);

/** true if a and b normalize to the same major.minor.patch triple. */
bool ota_manifest_version_eq(const char *a, const char *b);

#ifdef __cplusplus
}
#endif
