#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Runs once at boot, before ota_manager accepts checks. If the running image
 * is ESP_OTA_IMG_PENDING_VERIFY, evaluates required health items against a
 * hard deadline (CONFIG_AGENT_WIDGET_SELFTEST_WINDOW_SEC) and either calls
 * esp_ota_mark_app_valid_cancel_rollback() (returns ESP_OK) or
 * esp_ota_mark_app_invalid_rollback_and_reboot() (does not return). If the
 * running image is not pending-verify, returns ESP_OK immediately.
 */
esp_err_t boot_health_evaluate_and_commit(void);

/** Called by the ota_manager task loop to prove liveness to the self-test. */
void boot_health_note_ota_heartbeat(void);

/**
 * Releases the CONFIG_AGENT_WIDGET_SELFTEST_GATE_UART gate (T5 fixture only).
 * Invoked by app_console on a "health-continue" command. No-op otherwise.
 */
void boot_health_release_gate(void);

#ifdef __cplusplus
}
#endif
