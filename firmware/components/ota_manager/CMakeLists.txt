idf_component_register(
    SRCS "ota_manager.c" "ota_discovery.c" "ota_manifest.c" "ota_verifier.c" "ota_installer.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES app_update esp_https_ota esp_http_client json mbedtls boot_health ota_events trust_store esp-tls spi_flash
)
