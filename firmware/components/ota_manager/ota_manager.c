#include "ota_manager.h"

#include <string.h>

#include "boot_health.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "freertos/timers.h"
#include "ota_discovery.h"
#include "ota_events.h"
#include "ota_installer.h"
#include "ota_manifest.h"
#include "sdkconfig.h"

static const char *TAG = "ota_manager";

/* How long an AVAILABLE candidate waits for "install"/"cancel" before it
 * expires back to IDLE. Not part of the architecture's mandatory interface;
 * documented simplification for the QEMU drills, which always confirm
 * promptly. */
#define OTA_AVAILABLE_TIMEOUT_SEC 120

static QueueHandle_t s_trigger_queue;
static SemaphoreHandle_t s_state_mutex;
static TimerHandle_t s_periodic_timer;

static ota_status_t s_status = OTA_STATE_IDLE;
static ota_manifest_record_t s_candidate;
static bool s_have_candidate = false;
static volatile bool s_install_confirmed = false;
static volatile bool s_cancel_requested = false;

static void set_status(ota_status_t s)
{
    xSemaphoreTake(s_state_mutex, portMAX_DELAY);
    s_status = s;
    xSemaphoreGive(s_state_mutex);
}

static void periodic_timer_cb(TimerHandle_t t)
{
    (void)t;
    ota_manager_request_check(OTA_TRIGGER_TIMER);
}

static void ota_task(void *arg)
{
    (void)arg;
    ota_discovery_config_t discovery_cfg;
    strlcpy(discovery_cfg.releases_api_url, CONFIG_AGENT_WIDGET_RELEASES_API_URL,
            sizeof(discovery_cfg.releases_api_url));
    strlcpy(discovery_cfg.manifest_url, CONFIG_AGENT_WIDGET_MANIFEST_URL, sizeof(discovery_cfg.manifest_url));

    while (1) {
        ota_trigger_t trigger;
        if (xQueueReceive(s_trigger_queue, &trigger, pdMS_TO_TICKS(300)) != pdTRUE) {
            boot_health_note_ota_heartbeat();
            continue;
        }
        boot_health_note_ota_heartbeat();

        const esp_partition_t *running = esp_ota_get_running_partition();
        esp_ota_img_states_t running_state = ESP_OTA_IMG_UNDEFINED;
        esp_ota_get_state_partition(running, &running_state);
        if (running_state == ESP_OTA_IMG_PENDING_VERIFY) {
            ota_evt("OTA_BUSY", "reason=pending_verify");
            continue;
        }
        if (s_status != OTA_STATE_IDLE) {
            ota_evt("OTA_BUSY", "state=%s", ota_manager_status_str(s_status));
            continue;
        }

        set_status(OTA_STATE_CHECKING);
        ota_evt("CHECK_BEGIN", "trigger=%s", trigger == OTA_TRIGGER_TIMER ? "timer" : "uart");

        ota_manifest_record_t candidate;
        esp_err_t err = ota_discovery_check(&discovery_cfg, esp_app_get_description()->version, &candidate);
        if (err != ESP_OK) {
            set_status(OTA_STATE_IDLE);
            continue;
        }

        xSemaphoreTake(s_state_mutex, portMAX_DELAY);
        s_candidate = candidate;
        s_have_candidate = true;
        s_install_confirmed = false;
        s_cancel_requested = false;
        xSemaphoreGive(s_state_mutex);
        set_status(OTA_STATE_AVAILABLE);

        int64_t deadline = esp_timer_get_time() + (int64_t)OTA_AVAILABLE_TIMEOUT_SEC * 1000000;
        while (esp_timer_get_time() < deadline) {
            if (s_install_confirmed || s_cancel_requested) {
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(200));
            boot_health_note_ota_heartbeat();
        }

        bool confirmed = s_install_confirmed;
        bool cancelled = s_cancel_requested;
        s_have_candidate = false;

        if (cancelled || !confirmed) {
            ota_evt("OTA_STATE", "state=IDLE reason=%s version=%s",
                    cancelled ? "cancelled" : "expired", candidate.version);
            set_status(OTA_STATE_IDLE);
            continue;
        }

        set_status(OTA_STATE_DOWNLOADING);
        err = ota_installer_run(&candidate);
        if (err != ESP_OK) {
            set_status(OTA_STATE_FAILED);
            set_status(OTA_STATE_IDLE);
            continue;
        }

        ota_evt("REBOOT", "version=%s", candidate.version);
        vTaskDelay(pdMS_TO_TICKS(50)); /* let the serial line flush before reset */
        esp_restart();
    }
}

esp_err_t ota_manager_start(void)
{
    s_state_mutex = xSemaphoreCreateMutex();
    if (s_state_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }
    s_trigger_queue = xQueueCreate(1, sizeof(ota_trigger_t));
    if (s_trigger_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    s_periodic_timer = xTimerCreate("ota_periodic", pdMS_TO_TICKS(CONFIG_AGENT_WIDGET_CHECK_INTERVAL_SEC * 1000),
                                     pdTRUE, NULL, periodic_timer_cb);
    if (s_periodic_timer == NULL) {
        return ESP_ERR_NO_MEM;
    }

    BaseType_t ok = xTaskCreate(ota_task, "ota_manager", 16384, NULL, 5, NULL);
    if (ok != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

void ota_manager_arm_periodic(void)
{
    xTimerStart(s_periodic_timer, 0);
    ESP_LOGI(TAG, "periodic OTA checks armed (interval=%ds)", CONFIG_AGENT_WIDGET_CHECK_INTERVAL_SEC);
}

esp_err_t ota_manager_request_check(ota_trigger_t trigger)
{
    ota_trigger_t t = trigger;
    if (xQueueSend(s_trigger_queue, &t, 0) != pdTRUE) {
        ota_evt("OTA_BUSY", "trigger=%s reason=queue_full", trigger == OTA_TRIGGER_TIMER ? "timer" : "uart");
        return ESP_ERR_INVALID_STATE;
    }
    return ESP_OK;
}

esp_err_t ota_manager_confirm_install(void)
{
    xSemaphoreTake(s_state_mutex, portMAX_DELAY);
    bool ok = (s_status == OTA_STATE_AVAILABLE);
    if (ok) {
        s_install_confirmed = true;
    }
    xSemaphoreGive(s_state_mutex);
    return ok ? ESP_OK : ESP_ERR_INVALID_STATE;
}

esp_err_t ota_manager_cancel(void)
{
    xSemaphoreTake(s_state_mutex, portMAX_DELAY);
    bool ok = (s_status == OTA_STATE_AVAILABLE);
    if (ok) {
        s_cancel_requested = true;
    }
    xSemaphoreGive(s_state_mutex);
    return ok ? ESP_OK : ESP_ERR_INVALID_STATE;
}

ota_status_t ota_manager_status(void)
{
    xSemaphoreTake(s_state_mutex, portMAX_DELAY);
    ota_status_t s = s_status;
    xSemaphoreGive(s_state_mutex);
    return s;
}

const char *ota_manager_status_str(ota_status_t status)
{
    switch (status) {
    case OTA_STATE_IDLE: return "IDLE";
    case OTA_STATE_CHECKING: return "CHECKING";
    case OTA_STATE_AVAILABLE: return "AVAILABLE";
    case OTA_STATE_DOWNLOADING: return "DOWNLOADING";
    case OTA_STATE_FAILED: return "FAILED";
    default: return "UNKNOWN";
    }
}

void ota_manager_candidate_version(char *out, size_t out_len)
{
    xSemaphoreTake(s_state_mutex, portMAX_DELAY);
    if (s_have_candidate) {
        strlcpy(out, s_candidate.version, out_len);
    } else if (out_len > 0) {
        out[0] = '\0';
    }
    xSemaphoreGive(s_state_mutex);
}
