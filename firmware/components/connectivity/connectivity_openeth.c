// QEMU-only adapter: OpenCores Ethernet MAC + DHCP client. QEMU's ESP32-S3
// model does not emulate Wi-Fi; this is the supported network path per
// codex-architecture.md section 8.1.
#include "connectivity.h"

#include <string.h>

#include "esp_eth.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "ota_events.h"

static const char *TAG = "connectivity_openeth";

static EventGroupHandle_t s_events = NULL;
static volatile bool s_online = false;
static esp_eth_handle_t s_eth_handle = NULL;

static void on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    (void)arg;
    (void)base;
    (void)id;
    ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
    s_online = true;
    xEventGroupSetBits(s_events, CONNECTIVITY_CONNECTED_BIT);
    ota_evt("NET_UP", "adapter=openeth ip=" IPSTR, IP2STR(&event->ip_info.ip));
}

static void on_eth_event(void *arg, esp_event_base_t base, int32_t id, void *event_data)
{
    (void)arg;
    (void)base;
    (void)event_data;
    switch (id) {
    case ETHERNET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "link up");
        break;
    case ETHERNET_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "link down");
        s_online = false;
        xEventGroupClearBits(s_events, CONNECTIVITY_CONNECTED_BIT);
        break;
    default:
        break;
    }
}

esp_err_t connectivity_start(void)
{
    s_events = xEventGroupCreate();
    if (s_events == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_config_t netif_config = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&netif_config);

    eth_mac_config_t mac_config = ETH_MAC_DEFAULT_CONFIG();
    eth_phy_config_t phy_config = ETH_PHY_DEFAULT_CONFIG();
    phy_config.autonego_timeout_ms = 100;
    phy_config.phy_addr = -1;

    esp_eth_mac_t *mac = esp_eth_mac_new_openeth(&mac_config);
    esp_eth_phy_t *phy = esp_eth_phy_new_dp83848(&phy_config);

    esp_eth_config_t config = ETH_DEFAULT_CONFIG(mac, phy);
    ESP_ERROR_CHECK(esp_eth_driver_install(&config, &s_eth_handle));

    uint8_t mac_addr[6] = {0};
    ESP_ERROR_CHECK(esp_read_mac(mac_addr, ESP_MAC_ETH));
    ESP_ERROR_CHECK(esp_eth_ioctl(s_eth_handle, ETH_CMD_S_MAC_ADDR, mac_addr));

    esp_eth_netif_glue_handle_t glue = esp_eth_new_netif_glue(s_eth_handle);
    ESP_ERROR_CHECK(esp_netif_attach(netif, glue));

    ESP_ERROR_CHECK(esp_event_handler_register(ETH_EVENT, ESP_EVENT_ANY_ID, &on_eth_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_GOT_IP, &on_got_ip, NULL));

    ESP_ERROR_CHECK(esp_eth_start(s_eth_handle));
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
