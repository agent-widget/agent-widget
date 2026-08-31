#pragma once

#include <stddef.h>

#include "esp_err.h"
#include "ota_manifest.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Runs the advanced esp_https_ota sequence from codex-architecture.md 5.2:
 * signature verify (pre-download) -> begin/get_img_desc -> perform loop ->
 * pre-finish partition hash against the authenticated digest -> finish.
 *
 * On ESP_OK, the new image has been written and selected as the next boot
 * partition (esp_https_ota_finish() succeeded); the caller is responsible
 * for esp_restart(). On failure, the old boot selection is unchanged: no
 * esp_restart() should follow.
 */
esp_err_t ota_installer_run(const ota_manifest_record_t *candidate);

#ifdef __cplusplus
}
#endif
