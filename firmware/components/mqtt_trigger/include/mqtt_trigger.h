#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Starts the MQTT OTA-trigger client: connects to the broker (URI/credentials
 * from Kconfig), subscribes to `ota/announce` and `ota/{device_id}`, and on a
 * matching OTA notification parses the payload as a manifest record and offers
 * it to ota_manager (OTA_STATE_AVAILABLE). See docs/ota/11 for the channel
 * design. Returns immediately; connection happens asynchronously.
 */
esp_err_t mqtt_trigger_start(void);

#ifdef __cplusplus
}
#endif
