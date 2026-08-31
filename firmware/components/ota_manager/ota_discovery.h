#pragma once

#include "esp_err.h"
#include "ota_manifest.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char releases_api_url[256]; /* GitHub Releases API (or fixture equivalent) */
    char manifest_url[256];     /* signed manifest.json (or fixture equivalent) */
} ota_discovery_config_t;

/**
 * Performs the dual-channel check described in codex-architecture.md 4.2:
 * fetch the Releases API for the candidate version, fetch the signed
 * manifest for cryptographic metadata, and only trust a candidate whose
 * version both channels agree on and whose min_version the running version
 * satisfies. On ESP_OK, *out holds the trusted candidate (manifest URL and
 * crypto fields; RSA signature is NOT yet verified by this call).
 *
 * @return ESP_OK on a trusted, newer candidate; ESP_ERR_NOT_FOUND if there is
 *         none; ESP_FAIL on transport/parse errors.
 */
esp_err_t ota_discovery_check(const ota_discovery_config_t *cfg, const char *running_version,
                               ota_manifest_record_t *out);

#ifdef __cplusplus
}
#endif
