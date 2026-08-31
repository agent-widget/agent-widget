#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Emits one machine-parseable line to the console UART:
 *   AW_EVT seq=<n> event=<event> <fmt...>
 * seq is a monotonic counter shared by all callers. Never pass secrets or
 * full manifest signatures through this path.
 */
void ota_evt(const char *event, const char *fmt, ...);

/** Emits an "AW_CMD id=<id> result=<result>" acknowledgement line. */
void ota_cmd_ack(uint32_t id, const char *result);

/** Returns and increments the next command id, for callers assigning ids. */
uint32_t ota_events_next_cmd_id(void);

#ifdef __cplusplus
}
#endif
