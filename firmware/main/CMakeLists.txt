idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES app_runtime connectivity ota_manager boot_health app_console mqtt_trigger
)
