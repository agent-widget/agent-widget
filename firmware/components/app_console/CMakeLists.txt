idf_component_register(
    SRCS "app_console.c"
    INCLUDE_DIRS "include"
    REQUIRES app_update boot_health ota_events ota_manager
)
