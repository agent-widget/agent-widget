#include "boot_health_platform.h"

#include <stdbool.h>

#include "ota_events.h"

bool boot_health_platform_report(void)
{
    // Real display/touch/UI-heartbeat checks land with AW-002/AW-003 board
    // bring-up. Until then the board cannot prove these mandatory items, so
    // they report BLOCKED and the overall self-test verdict must be FAIL —
    // never mark an image valid without hardware coverage.
    ota_evt("SELFTEST_ITEM", "item=display result=BLOCKED reason=not_yet_implemented");
    ota_evt("SELFTEST_ITEM", "item=touch result=BLOCKED reason=not_yet_implemented");
    return false;
}
