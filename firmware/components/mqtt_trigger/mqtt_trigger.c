#include "mqtt_trigger.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "mqtt_client.h"
#include "ota_events.h"
#include "ota_manifest.h"
#include "ota_manager.h"
#include "sdkconfig.h"

static const char *TAG = "mqtt_trigger";

static esp_mqtt_client_handle_t s_client = NULL;

static void mqtt_handler(void *handler_arg, esp_event_base_t base, int32_t event_id, void *event_data)
{
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)event_data;
    if (event == NULL) {
        return;
    }

    if (event_id == MQTT_EVENT_CONNECTED) {
        ESP_LOGI(TAG, "connected to broker, subscribing to ota topics");
        esp_mqtt_client_subscribe(s_client, "ota/announce", 1);
        char target[64];
        snprintf(target, sizeof(target), "ota/%s", CONFIG_AGENT_WIDGET_MQTT_DEVICE_ID);
        esp_mqtt_client_subscribe(s_client, target, 1);
        return;
    }
    if (event_id == MQTT_EVENT_DISCONNECTED) {
        ESP_LOGW(TAG, "disconnected from broker (auto-reconnect enabled)");
        return;
    }
    if (event_id != MQTT_EVENT_DATA || event->data == NULL || event->data_len <= 0) {
        return;
    }

    /* Only OTA notification topics. */
    const char *announce_topic = "ota/announce";
    if (!(event->topic_len == (int)strlen(announce_topic)
          && strncmp(event->topic, announce_topic, (size_t)event->topic_len) == 0)) {
        return;
    }

    /* Wrap the payload as a single-record manifest and reuse the strict parser
     * (version/url/size/sha256/signature normalization + HTTPS + length gates). */
    size_t buf_len = (size_t)event->data_len + 64;
    char *buf = malloc(buf_len);
    if (buf == NULL) {
        ESP_LOGE(TAG, "OOM parsing OTA notification (%d bytes)", event->data_len);
        return;
    }
    int n = snprintf(buf, buf_len, "{\"releases\":[%.*s]}", event->data_len, event->data);
    if (n <= 0) {
        free(buf);
        return;
    }

    ota_manifest_record_t recs[1];
    size_t count = 0;
    esp_err_t err = ota_manifest_parse(buf, (size_t)n, recs, 1, &count);
    free(buf);
    if (err != ESP_OK || count == 0) {
        ota_evt("MQTT_NOTIFY", "result=parse_failed");
        return;
    }

    ota_evt("MQTT_NOTIFY", "result=ok version=%s trigger=mqtt", recs[0].version);
    err = ota_manager_offer_candidate(&recs[0]);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "offer_candidate failed: %s", esp_err_to_name(err));
    }
}

esp_err_t mqtt_trigger_start(void)
{
    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = CONFIG_AGENT_WIDGET_MQTT_URI,
        .credentials.username = CONFIG_AGENT_WIDGET_MQTT_USER,
        .credentials.authentication.password = CONFIG_AGENT_WIDGET_MQTT_PASS,
    };
    s_client = esp_mqtt_client_init(&cfg);
    if (s_client == NULL) {
        ESP_LOGE(TAG, "esp_mqtt_client_init failed");
        return ESP_ERR_NO_MEM;
    }
    esp_mqtt_client_register_event(s_client, MQTT_EVENT_ANY, mqtt_handler, NULL);
    esp_err_t err = esp_mqtt_client_start(s_client);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_mqtt_client_start failed: %s", esp_err_to_name(err));
        return err;
    }
    ota_evt("MQTT_START", "uri=%s user=%s device=%s",
            CONFIG_AGENT_WIDGET_MQTT_URI, CONFIG_AGENT_WIDGET_MQTT_USER,
            CONFIG_AGENT_WIDGET_MQTT_DEVICE_ID);
    return ESP_OK;
}
