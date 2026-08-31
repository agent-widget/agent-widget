#include "boot_health_platform.h"

#include <stdbool.h>

#include "ota_events.h"

bool boot_health_platform_report(void)
{
    // QEMU emulates neither the AXS15231B display/touch nor the touch
    // controller; must never be reported as PASS.
    ota_evt("SELFTEST_ITEM", "item=display result=NOT_APPLICABLE");
    ota_evt("SELFTEST_ITEM", "item=touch result=NOT_APPLICABLE");
    return true;
}
