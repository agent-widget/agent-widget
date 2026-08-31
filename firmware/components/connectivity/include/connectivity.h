#pragma once

#include <stdbool.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CONNECTIVITY_CONNECTED_BIT (1 << 0)
#define CONNECTIVITY_FAILED_BIT    (1 << 1)

/**
 * Starts the build-selected connectivity adapter (Wi-Fi on the board, an
 * OpenCores Ethernet netif under QEMU) and returns immediately; it does not
 * block until an IP address is obtained. boot_health polls
 * connectivity_is_online() against its own deadline.
 */
esp_err_t connectivity_start(void);

bool connectivity_is_online(void);

EventGroupHandle_t connectivity_events(void);

#ifdef __cplusplus
}
#endif
