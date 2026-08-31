// Board adapter: station-mode Wi-Fi. Not exercised by the QEMU drills (QEMU
// has no ESP32-S3 Wi-Fi emulation); real-device acceptance is AW-002/AW-003.
#include "connectivity.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "ota_events.h"

static const char *TAG = "connectivity_wifi";

static EventGroupHandle_t s_events = NULL;
static volatile bool s_online = false;

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    (void)arg;
    (void)event_data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_online = false;
        xEventGroupClearBits(s_events, CONNECTIVITY_CONNECTED_BIT);
        ESP_LOGW(TAG, "disconnected, retrying");
        esp_wifi_connect();
    }
}

static void on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    (void)arg;
    (void)base;
    (void)id;
    ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
    s_online = true;
    xEventGroupSetBits(s_events, CONNECTIVITY_CONNECTED_BIT);
    ota_evt("NET_UP", "adapter=wifi ip=" IPSTR, IP2STR(&event->ip_info.ip));
}

esp_err_t connectivity_start(void)
{
    s_events = xEventGroupCreate();
    if (s_events == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &on_wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &on_got_ip, NULL));

    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, CONFIG_AGENT_WIDGET_WIFI_SSID, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, CONFIG_AGENT_WIDGET_WIFI_PASSWORD, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    return ESP_OK;
}

bool connectivity_is_online(void)
{
    return s_online;
}

EventGroupHandle_t connectivity_events(void)
{
    return s_events;
}
