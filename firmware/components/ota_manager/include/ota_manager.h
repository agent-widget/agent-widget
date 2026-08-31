#pragma once

#include <stddef.h>

#include "esp_err.h"
#include "ota_manifest.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    OTA_TRIGGER_TIMER = 0,
    OTA_TRIGGER_UART,
    OTA_TRIGGER_MQTT,
} ota_trigger_t;

typedef enum {
    OTA_STATE_IDLE = 0,
    OTA_STATE_CHECKING,
    OTA_STATE_AVAILABLE,
    OTA_STATE_DOWNLOADING,
    OTA_STATE_FAILED,
} ota_status_t;

/** Creates the OTA task, queue, and periodic timer. The timer does not start
 *  ticking until ota_manager_arm_periodic() is called (after boot commit). */
esp_err_t ota_manager_start(void);

/** Arms the periodic check timer. Call only after boot_health has committed
 *  the running image (i.e. it is no longer PENDING_VERIFY). */
void ota_manager_arm_periodic(void);

/**
 * Non-blocking; posts to a length-one queue. Returns ESP_ERR_INVALID_STATE
 * (and emits OTA_BUSY) if a check/install is already active.
 */
esp_err_t ota_manager_request_check(ota_trigger_t trigger);

/** Valid only when ota_manager_status() == OTA_STATE_AVAILABLE. */
esp_err_t ota_manager_confirm_install(void);

/** Cancels an AVAILABLE candidate that hasn't started downloading. */
esp_err_t ota_manager_cancel(void);

/**
 * Offers a candidate found by an external trigger source (MQTT push
 * notification). Copies the record and transitions to OTA_STATE_AVAILABLE;
 * the caller's buffer can be released afterwards. Fails with
 * ESP_ERR_INVALID_STATE if a check/install is already active, or
 * ESP_ERR_INVALID_ARG if the record fails basic sanity checks (version
 * non-empty, HTTPS url, size>0, sha256 set, signature set). The candidate
 * still requires ota_manager_confirm_install() (or auto-confirm policy)
 * before downloading.
 */
esp_err_t ota_manager_offer_candidate(const ota_manifest_record_t *rec);

ota_status_t ota_manager_status(void);
const char *ota_manager_status_str(ota_status_t status);

/** version of the AVAILABLE candidate, or "" if none. Buffer must be >= 32B. */
void ota_manager_candidate_version(char *out, size_t out_len);

#ifdef __cplusplus
}
#endif
