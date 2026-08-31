#include "boot_health.h"

#include <stdatomic.h>
#include <stdbool.h>
#include <string.h>

#include "boot_health_platform.h"
#include "connectivity.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ota_events.h"
#include "sdkconfig.h"

static const char *TAG = "boot_health";

static _Atomic uint32_t s_heartbeat_count = 0;
static _Atomic int64_t s_first_heartbeat_us = -1;
static _Atomic int64_t s_last_heartbeat_us = -1;
static _Atomic bool s_gate_released = false;

void boot_health_note_ota_heartbeat(void)
{
    int64_t now = esp_timer_get_time();
    int64_t expected = -1;
    atomic_compare_exchange_strong(&s_first_heartbeat_us, &expected, now);
    atomic_store(&s_last_heartbeat_us, now);
    atomic_fetch_add(&s_heartbeat_count, 1);
}

void boot_health_release_gate(void)
{
    atomic_store(&s_gate_released, true);
}

static bool ota_task_alive_item(void)
{
    uint32_t count = atomic_load(&s_heartbeat_count);
    int64_t first = atomic_load(&s_first_heartbeat_us);
    int64_t last = atomic_load(&s_last_heartbeat_us);
    return count >= 2 && first >= 0 && (last - first) >= 1000000;
}

static const char *ota_state_str(esp_ota_img_states_t state)
{
    switch (state) {
    case ESP_OTA_IMG_NEW: return "NEW";
    case ESP_OTA_IMG_PENDING_VERIFY: return "PENDING_VERIFY";
    case ESP_OTA_IMG_VALID: return "VALID";
    case ESP_OTA_IMG_INVALID: return "INVALID";
    case ESP_OTA_IMG_ABORTED: return "ABORTED";
    default: return "UNDEFINED";
    }
}

esp_err_t boot_health_evaluate_and_commit(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_app_desc_t *desc = esp_app_get_description();
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_err_t state_err = esp_ota_get_state_partition(running, &state);

    ota_evt("BOOT", "version=%s running=%s state=%s",
            desc->version, running->label,
            state_err == ESP_OK ? ota_state_str(state) : "UNKNOWN");
    ota_evt("PARTITIONS", "running=%s next=%s",
            running->label,
            esp_ota_get_next_update_partition(NULL) ? esp_ota_get_next_update_partition(NULL)->label : "none");

    if (state_err != ESP_OK || state != ESP_OTA_IMG_PENDING_VERIFY) {
        ESP_LOGI(TAG, "running image already committed (state=%s); skipping self-test",
                 state_err == ESP_OK ? ota_state_str(state) : "unknown");
        return ESP_OK;
    }

    int deadline_sec = CONFIG_AGENT_WIDGET_SELFTEST_WINDOW_SEC;
    ota_evt("SELFTEST_BEGIN", "state=PENDING_VERIFY deadline_sec=%d", deadline_sec);

    bool version_ok = desc->version[0] != '\0';
    ota_evt("SELFTEST_ITEM", "item=version_selfreport result=%s value=%s",
            version_ok ? "PASS" : "FAIL", desc->version);

    bool forced_fail = false;
#if CONFIG_AGENT_WIDGET_TEST_HOOKS && CONFIG_AGENT_WIDGET_SELFTEST_FORCE_FAIL
    forced_fail = true;
    ota_evt("SELFTEST_ITEM", "item=forced result=FAIL test_hook=forced_failure");
#endif

    int64_t deadline_us = esp_timer_get_time() + (int64_t)deadline_sec * 1000000;
    bool connectivity_ok = false;
    bool task_ok = false;
    while (!forced_fail && esp_timer_get_time() < deadline_us) {
        connectivity_ok = connectivity_is_online();
        task_ok = ota_task_alive_item();
        if (connectivity_ok && task_ok) {
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(200));
    }
    ota_evt("SELFTEST_ITEM", "item=connectivity result=%s", connectivity_ok ? "PASS" : "FAIL");
    ota_evt("SELFTEST_ITEM", "item=ota_task_alive result=%s", task_ok ? "PASS" : "FAIL");
    bool platform_ok = boot_health_platform_report();
    ota_evt("SELFTEST_ITEM", "item=platform result=%s", platform_ok ? "PASS" : "FAIL");

    bool overall_pass = !forced_fail && version_ok && connectivity_ok && task_ok && platform_ok;

    if (overall_pass) {
#if CONFIG_AGENT_WIDGET_TEST_HOOKS && CONFIG_AGENT_WIDGET_SELFTEST_GATE_UART
        ota_evt("SELFTEST_WAIT_GATE", "waiting for health-continue command");
        while (!atomic_load(&s_gate_released)) {
            vTaskDelay(pdMS_TO_TICKS(200));
        }
#endif
        ESP_ERROR_CHECK(esp_ota_mark_app_valid_cancel_rollback());
        ota_evt("MARK_VALID", "version=%s", desc->version);
        return ESP_OK;
    }

    ota_evt("MARK_INVALID", "version=%s reason=selftest_failed", desc->version);
    ESP_LOGE(TAG, "self-test failed, rolling back to previous valid image");
    esp_ota_mark_app_invalid_rollback_and_reboot();
    // Does not return on success; if it does, something is badly wrong.
    return ESP_FAIL;
}
