if(CONFIG_AGENT_WIDGET_PLATFORM_QEMU)
    set(agent_widget_platform_src "boot_health_qemu.c")
else()
    set(agent_widget_platform_src "boot_health_board.c")
endif()

idf_component_register(
    SRCS "boot_health.c" "${agent_widget_platform_src}"
    INCLUDE_DIRS "include"
    REQUIRES app_update connectivity ota_events esp_timer
)
