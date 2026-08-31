idf_component_register(
    SRCS "mqtt_trigger.c"
    INCLUDE_DIRS "include"
    REQUIRES mqtt ota_manager
)
