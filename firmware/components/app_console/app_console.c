#include "app_console.h"

#include <stdio.h>
#include <string.h>

#include "boot_health.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ota_events.h"
#include "ota_manager.h"

static const char *TAG = "app_console";

static void print_help(void)
{
    printf("commands: help | status | check | install | cancel | health | health-continue\n");
}

static void print_status(void)
{
    const esp_app_desc_t *desc = esp_app_get_description();
    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_ota_get_state_partition(running, &state);
    char candidate[32] = {0};
    ota_manager_candidate_version(candidate, sizeof(candidate));

    const char *state_str = "UNKNOWN";
    switch (state) {
    case ESP_OTA_IMG_NEW: state_str = "NEW"; break;
    case ESP_OTA_IMG_PENDING_VERIFY: state_str = "PENDING_VERIFY"; break;
    case ESP_OTA_IMG_VALID: state_str = "VALID"; break;
    case ESP_OTA_IMG_INVALID: state_str = "INVALID"; break;
    case ESP_OTA_IMG_ABORTED: state_str = "ABORTED"; break;
    default: break;
    }

    printf("version=%s running=%s next=%s image_state=%s ota_state=%s candidate=%s\n",
           desc->version, running->label, next ? next->label : "none", state_str,
           ota_manager_status_str(ota_manager_status()), candidate);
}

static void handle_line(char *line)
{
    /* Trim trailing CR/LF/whitespace. */
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r' || line[len - 1] == ' ')) {
        line[--len] = '\0';
    }
    if (len == 0) {
        return;
    }

    uint32_t id = ota_events_next_cmd_id();

    if (strcmp(line, "help") == 0) {
        print_help();
        ota_cmd_ack(id, "ok");
    } else if (strcmp(line, "status") == 0) {
        print_status();
        ota_cmd_ack(id, "ok");
    } else if (strcmp(line, "check") == 0 || strcmp(line, "c") == 0) {
        esp_err_t err = ota_manager_request_check(OTA_TRIGGER_UART);
        ota_cmd_ack(id, err == ESP_OK ? "ok" : "busy");
    } else if (strcmp(line, "install") == 0 || strcmp(line, "u") == 0) {
        esp_err_t err = ota_manager_confirm_install();
        ota_cmd_ack(id, err == ESP_OK ? "ok" : "invalid_state");
    } else if (strcmp(line, "cancel") == 0) {
        esp_err_t err = ota_manager_cancel();
        ota_cmd_ack(id, err == ESP_OK ? "ok" : "invalid_state");
    } else if (strcmp(line, "health") == 0) {
        print_status();
        ota_cmd_ack(id, "ok");
    } else if (strcmp(line, "health-continue") == 0) {
        boot_health_release_gate();
        ota_cmd_ack(id, "ok");
    } else {
        printf("unknown command: %s\n", line);
        ota_cmd_ack(id, "unknown_command");
    }
}

static void console_task(void *arg)
{
    (void)arg;
    char line[128];
    while (1) {
        if (fgets(line, sizeof(line), stdin) != NULL) {
            handle_line(line);
        } else {
            vTaskDelay(pdMS_TO_TICKS(50));
        }
    }
}

esp_err_t app_console_start(void)
{
    BaseType_t ok = xTaskCreate(console_task, "app_console", 4096, NULL, 4, NULL);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "failed to create console task");
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
