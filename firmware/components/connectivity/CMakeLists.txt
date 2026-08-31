if(CONFIG_AGENT_WIDGET_PLATFORM_QEMU)
    set(agent_widget_adapter_src "connectivity_openeth.c")
else()
    set(agent_widget_adapter_src "connectivity_wifi.c")
endif()

# NOTE: REQUIRES is intentionally unconditional (lists both adapters' deps).
# ESP-IDF's early "expand component requirements" pass does not reliably see
# custom project Kconfig symbols yet, so gating REQUIRES on
# CONFIG_AGENT_WIDGET_PLATFORM_QEMU here silently drops esp_eth from the
# computed requirements list even though the (correctly config-gated) SRCS
# still compiles connectivity_openeth.c. Only SRCS is conditional.
idf_component_register(
    SRCS "${agent_widget_adapter_src}"
    INCLUDE_DIRS "include"
    REQUIRES esp_netif esp_event ota_events esp_eth esp_wifi nvs_flash
)
