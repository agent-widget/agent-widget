// Composition root only: boot order and task ownership. No manifest parsing
// or OTA transitions live here; see components/ota_manager.
#include "app_console.h"
#include "app_runtime.h"
#include "boot_health.h"
#include "connectivity.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "mqtt_trigger.h"
#include "ota_manager.h"

static const char *TAG = "app_main";

void app_main(void)
{
    ESP_ERROR_CHECK(app_runtime_init());
    ESP_ERROR_CHECK(connectivity_start());
    ESP_ERROR_CHECK(ota_manager_start());
    ESP_ERROR_CHECK(app_console_start());
    ESP_ERROR_CHECK(mqtt_trigger_start());

    // Blocks (self-test window) only if the running image is
    // PENDING_VERIFY; reboots via esp_ota_mark_app_invalid_rollback_and_reboot()
    // on failure and does not return in that case.
    ESP_ERROR_CHECK(boot_health_evaluate_and_commit());

    ota_manager_arm_periodic();
    ESP_LOGI(TAG, "boot commit complete; periodic OTA checks armed");
}
