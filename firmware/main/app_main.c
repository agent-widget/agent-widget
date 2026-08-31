// Composition root only: boot order and task ownership. No manifest parsing
// or OTA transitions live here; see components/ota_manager.
#include "app_console.h"
#include "app_runtime.h"
#include "boot_health.h"
#include "connectivity.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "ota_manager.h"

static const char *TAG = "app_main";

void app_main(void)
{
    ESP_ERROR_CHECK(app_runtime_init());
    ESP_ERROR_CHECK(connectivity_start());
    ESP_ERROR_CHECK(ota_manager_start());
    ESP_ERROR_CHECK(app_console_start());

    // TEMP DEBUG: verify esp_flash_read correctness on a non-just-written region
    {
        const esp_partition_t *run = esp_ota_get_running_partition();
        uint8_t probe[16];
        if (esp_partition_read(run, 0, probe, sizeof(probe)) == ESP_OK) {
            ESP_LOGI("DBG_READ", "running=%s addr=0x%x read16=%02x%02x %02x%02x %02x%02x %02x%02x",
                     run->label, (unsigned)run->address,
                     probe[0], probe[1], probe[2], probe[3], probe[4], probe[5], probe[6], probe[7]);
        } else {
            ESP_LOGE("DBG_READ", "esp_partition_read failed");
        }
    }

    // Blocks (self-test window) only if the running image is
    // PENDING_VERIFY; reboots via esp_ota_mark_app_invalid_rollback_and_reboot()
    // on failure and does not return in that case.
    ESP_ERROR_CHECK(boot_health_evaluate_and_commit());

    ota_manager_arm_periodic();
    ESP_LOGI(TAG, "boot commit complete; periodic OTA checks armed");
}
