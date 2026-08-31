#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Starts the UART0 line-command task (help/status/check/install/cancel/
 *  health/health-continue). Every command emits "AW_CMD id=<n> result=..."
 *  on completion. */
esp_err_t app_console_start(void);

#ifdef __cplusplus
}
#endif
