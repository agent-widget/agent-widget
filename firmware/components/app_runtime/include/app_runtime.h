#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** NVS init with the standard erase-and-retry recovery. Call first, before
 *  any other component that touches NVS (Wi-Fi, OTA diagnostics). */
esp_err_t app_runtime_init(void);

#ifdef __cplusplus
}
#endif
