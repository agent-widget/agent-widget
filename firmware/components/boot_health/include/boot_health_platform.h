#pragma once

// Internal seam between boot_health.c and the board/QEMU report files. Not a
// public component interface.

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Emits the platform-specific SELFTEST_ITEM events and returns the platform
 *  verdict for the mandatory items boot_health.c cannot evaluate itself:
 *   - board: display + touch must actually PASS (true); BLOCKED/not-yet
 *     implemented must return false so the image fails self-test and rolls
 *     back rather than being made valid without hardware coverage.
 *   - QEMU:  both are NOT_APPLICABLE and return true (nothing to check). */
bool boot_health_platform_report(void);

#ifdef __cplusplus
}
#endif
