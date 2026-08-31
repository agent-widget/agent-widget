#include "ota_verifier.h"

#include <string.h>

#include "esp_log.h"
#include "mbedtls/rsa.h"
#include "mbedtls/sha256.h"
#include "ota_signing_pubkey.h"
#include "spi_flash_mmap.h"

static const char *TAG = "ota_verifier";

esp_err_t ota_verifier_check_signature(const uint8_t digest[32], const uint8_t *sig, size_t sig_len)
{
    if (sig == NULL || digest == NULL || sig_len != 256) {
        ESP_LOGE(TAG, "invalid signature length %u (want 256)", (unsigned)sig_len);
        return ESP_ERR_INVALID_SIZE;
    }

    mbedtls_rsa_context rsa;
    mbedtls_rsa_init(&rsa);

    esp_err_t ret = ESP_FAIL;
    int mret = mbedtls_rsa_import_raw(&rsa,
                                       OTA_SIGNING_PUBKEY_N, sizeof(OTA_SIGNING_PUBKEY_N),
                                       NULL, 0, NULL, 0, NULL, 0,
                                       OTA_SIGNING_PUBKEY_E, sizeof(OTA_SIGNING_PUBKEY_E));
    if (mret != 0) {
        ESP_LOGE(TAG, "rsa_import_raw failed: -0x%04x", -mret);
        goto done;
    }
    mret = mbedtls_rsa_complete(&rsa);
    if (mret != 0) {
        ESP_LOGE(TAG, "rsa_complete failed: -0x%04x", -mret);
        goto done;
    }
    mret = mbedtls_rsa_set_padding(&rsa, MBEDTLS_RSA_PKCS_V15, MBEDTLS_MD_SHA256);
    if (mret != 0) {
        ESP_LOGE(TAG, "rsa_set_padding failed: -0x%04x", -mret);
        goto done;
    }
    mret = mbedtls_rsa_pkcs1_verify(&rsa, MBEDTLS_MD_SHA256, 32, digest, sig);
    if (mret != 0) {
        ESP_LOGW(TAG, "signature verify failed: -0x%04x", -mret);
        ret = ESP_FAIL;
    } else {
        ret = ESP_OK;
    }

done:
    mbedtls_rsa_free(&rsa);
    return ret;
}

esp_err_t ota_verifier_sha256_partition(const esp_partition_t *part, size_t len, uint8_t out_digest[32])
{
    if (part == NULL || out_digest == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    /* Prefer mmap: on QEMU (esp32s3 model) esp_flash_read returns offset data
     * right after a write (cache coherency bug); the boot path (which mmaps
     * flash) reads correctly, so hash via mmap when possible. */
    const size_t page = 0x10000; /* CONFIG_SPI_FLASH_MMU_PAGE_SIZE = 64 KiB */
    size_t mmap_len = ((len + page - 1) / page) * page;
    const void *map_ptr = NULL;
    spi_flash_mmap_handle_t map_handle = 0;
    if (spi_flash_mmap(part->address, mmap_len, SPI_FLASH_MMAP_DATA, &map_ptr, &map_handle) == ESP_OK) {
        mbedtls_sha256((const uint8_t *)map_ptr, len, out_digest, 0);
        spi_flash_munmap(map_handle);
        return ESP_OK;
    } else {
        ESP_LOGW(TAG, "spi_flash_mmap failed for addr=0x%x len=%u — falling back to esp_partition_read", (unsigned)part->address, (unsigned)mmap_len);
    }

    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    mbedtls_sha256_starts(&ctx, 0);

    uint8_t buf[1024];
    size_t remaining = len;
    size_t offset = 0;
    esp_err_t err = ESP_OK;
    while (remaining > 0) {
        size_t chunk = remaining < sizeof(buf) ? remaining : sizeof(buf);
        err = esp_partition_read(part, offset, buf, chunk);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_partition_read failed at offset %u: %s", (unsigned)offset, esp_err_to_name(err));
            break;
        }
        if (offset == 0 || offset == 0x10000 || offset == 0x20000 || offset == 0x30000 || offset == 0x3f000 || offset == 0x40000) {
            ESP_LOGI(TAG, "HASH_DEBUG off=0x%x part=%s addr=0x%x first16=%02x%02x%02x%02x %02x%02x%02x%02x %02x%02x%02x%02x %02x%02x%02x%02x",
                     (unsigned)offset, part->label, (unsigned)part->address,
                     buf[0], buf[1], buf[2], buf[3], buf[4], buf[5], buf[6], buf[7],
                     buf[8], buf[9], buf[10], buf[11], buf[12], buf[13], buf[14], buf[15]);
        }
        mbedtls_sha256_update(&ctx, buf, chunk);
        offset += chunk;
        remaining -= chunk;
    }
    if (err == ESP_OK) {
        mbedtls_sha256_finish(&ctx, out_digest);
    }
    mbedtls_sha256_free(&ctx);
    return err;
}
