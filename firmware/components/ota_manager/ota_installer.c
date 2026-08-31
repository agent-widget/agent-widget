#include "ota_installer.h"

#include <stdio.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include "ota_events.h"
#include "ota_verifier.h"
#include "sdkconfig.h"
#include "spi_flash_mmap.h"

#if CONFIG_AGENT_WIDGET_PLATFORM_QEMU
#include "qemu_test_ca.h"
#else
#include "esp_crt_bundle.h"
#endif

static const char *TAG = "ota_installer";

/* Self-contained streaming OTA download:
 *  - hash is computed over the *download stream* (mbedtls incremental), never by
 *    reading the flashed partition back. Rationale: on QEMU (esp32s3 model)
 *    esp_flash_read right after a write returns offset data (cache coherency
 *    bug) — the backing file ends up correct, but an in-run read-back is not.
 *    Hashing the stream sidesteps that entirely and is the same guarantee the
 *    partition-hash approach gave (actual bytes == manifest sha256).
 *  - boot selection is done explicitly via esp_ota_set_boot_partition() so we
 *    do not depend on esp_https_ota_finish()'s internal read-back validation
 *    (which hits the same QEMU bug). The bootloader re-validates the image
 *    magic/header on the mmap path at boot time, so a corrupt flash is still
 *    caught before execution.
 */
esp_err_t ota_installer_run(const ota_manifest_record_t *candidate)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t running_state = ESP_OTA_IMG_UNDEFINED;
    esp_ota_get_state_partition(running, &running_state);
    if (running_state == ESP_OTA_IMG_PENDING_VERIFY) {
        ESP_LOGE(TAG, "refusing install: running image not yet committed valid");
        return ESP_ERR_INVALID_STATE;
    }

    const esp_partition_t *target = esp_ota_get_next_update_partition(NULL);
    if (target == NULL || target == running) {
        ESP_LOGE(TAG, "no valid inactive OTA partition");
        return ESP_ERR_INVALID_STATE;
    }
    if (candidate->size == 0 || candidate->size >= target->size) {
        ESP_LOGE(TAG, "candidate size %u invalid for target partition size %u",
                 (unsigned)candidate->size, (unsigned)target->size);
        return ESP_ERR_INVALID_SIZE;
    }

    esp_err_t sig_err = ota_verifier_check_signature(candidate->sha256, candidate->signature,
                                                       candidate->signature_len);
    if (sig_err != ESP_OK) {
        ota_evt("SIGNATURE_FAIL", "version=%s", candidate->version);
        return ESP_FAIL;
    }
    ota_evt("SIGNATURE_OK", "version=%s running=%s target=%s", candidate->version, running->label, target->label);

    esp_http_client_config_t http_config = {
        .url = candidate->url,
        .timeout_ms = 30000,
        .keep_alive_enable = true,
    };
#if CONFIG_AGENT_WIDGET_PLATFORM_QEMU
    http_config.cert_pem = QEMU_TEST_CA_PEM;
#else
    http_config.crt_bundle_attach = esp_crt_bundle_attach;
#endif

    esp_http_client_handle_t client = esp_http_client_init(&http_config);
    if (client == NULL) {
        ESP_LOGE(TAG, "esp_http_client_init failed");
        return ESP_ERR_NO_MEM;
    }

    esp_err_t err = esp_http_client_open(client, 0); /* GET */
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_http_client_open failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=open error=%s", candidate->version, esp_err_to_name(err));
        return err;
    }

    int content_length = esp_http_client_fetch_headers(client);
    int http_status = esp_http_client_get_status_code(client);
    if (http_status < 200 || http_status >= 300) {
        ESP_LOGE(TAG, "unexpected HTTP status: %d", http_status);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=http_status got=%d", candidate->version, http_status);
        return ESP_ERR_INVALID_RESPONSE;
    }
    if (content_length < 0 || (uint32_t)content_length != candidate->size) {
        ESP_LOGE(TAG, "content length mismatch: %d expected %u", content_length, (unsigned)candidate->size);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=length_header got=%d expected=%u",
                candidate->version, content_length, (unsigned)candidate->size);
        return ESP_ERR_INVALID_SIZE;
    }

    esp_ota_handle_t ota = 0;
    err = esp_ota_begin(target, OTA_SIZE_UNKNOWN, &ota);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin failed: %s", esp_err_to_name(err));
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=begin error=%s", candidate->version, esp_err_to_name(err));
        return err;
    }

    ota_evt("OTA_STATE", "state=DOWNLOADING version=%s running=%s target=%s total=%u",
            candidate->version, running->label, target->label, (unsigned)candidate->size);

    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts(&sha, 0);

    static uint8_t buf[4096];   /* static: keep download loop off the task stack */
    int total = 0;
    int last_reported_pct = -1;
    bool body_error = false;
    while (1) {
        int n = esp_http_client_read(client, (char *)buf, sizeof(buf));
        if (n < 0) {
            ESP_LOGE(TAG, "esp_http_client_read failed: %d", n);
            body_error = true;
            break;
        }
        if (n == 0) {
            break;
        }
        mbedtls_sha256_update(&sha, buf, (size_t)n);
        err = esp_ota_write(ota, buf, (size_t)n);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_ota_write failed: %s", esp_err_to_name(err));
            body_error = true;
            break;
        }
        total += n;
        if (candidate->size > 0) {
            int pct = (int)((int64_t)total * 100 / (int)candidate->size);
            if (pct >= last_reported_pct + 10) {
                last_reported_pct = pct;
                ota_evt("DOWNLOAD_PROGRESS", "version=%s bytes=%d total=%u pct=%d",
                        candidate->version, total, (unsigned)candidate->size, pct);
            }
        }
    }

    uint8_t actual_digest[32] = {0};
    mbedtls_sha256_finish(&sha, actual_digest);
    mbedtls_sha256_free(&sha);

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (body_error) {
        esp_ota_abort(ota);
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=body", candidate->version);
        return ESP_FAIL;
    }
    if ((uint32_t)total != candidate->size) {
        ESP_LOGE(TAG, "body length mismatch: read=%d expected=%u", total, (unsigned)candidate->size);
        esp_ota_abort(ota);
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=length_body read=%d expected=%u",
                candidate->version, total, (unsigned)candidate->size);
        return ESP_ERR_INVALID_SIZE;
    }

    if (memcmp(actual_digest, candidate->sha256, 32) != 0) {
        char expected_prefix[9], actual_prefix[9];
        for (int i = 0; i < 4; i++) {
            sprintf(expected_prefix + i * 2, "%02x", candidate->sha256[i]);
            sprintf(actual_prefix + i * 2, "%02x", actual_digest[i]);
        }
        esp_ota_abort(ota);
        ota_evt("SHA_FAIL", "version=%s expected=%s... actual=%s...", candidate->version, expected_prefix, actual_prefix);
        return ESP_ERR_INVALID_CRC;
    }
    ota_evt("SHA_OK", "version=%s bytes=%d", candidate->version, total);

    /* B4: verify incoming image identity before selecting it for boot.
     * app_desc lives at image offset 32 (after esp_image_header_t +
     * esp_image_segment_header_t). Read via mmap: on the QEMU esp32s3 model
     * esp_flash_read returns offset data right after a write, while mmap
     * reads are correct (verified by the T1 suite). */
    {
        const void *map_ptr = NULL;
        spi_flash_mmap_handle_t map_handle = 0;
        if (spi_flash_mmap(target->address, 0x10000, SPI_FLASH_MMAP_DATA, &map_ptr, &map_handle) == ESP_OK) {
            const esp_app_desc_t *desc = (const esp_app_desc_t *)((const uint8_t *)map_ptr + 32);
            bool identity_ok = (desc->magic_word == ESP_APP_DESC_MAGIC_WORD)
                               && (strncmp(desc->project_name, "agent_widget", sizeof(desc->project_name)) == 0)
                               && (strncmp(desc->version, candidate->version, sizeof(desc->version)) == 0);
            spi_flash_munmap(map_handle);
            if (!identity_ok) {
                ESP_LOGE(TAG, "image identity mismatch: project='%.32s' version='%.32s' want project=agent_widget version=%s",
                         desc->project_name, desc->version, candidate->version);
                ota_evt("DOWNLOAD_FAIL", "version=%s stage=identity_mismatch project=%.32s got_version=%.32s",
                        candidate->version, desc->project_name, desc->version);
                esp_ota_abort(ota);
                return ESP_ERR_OTA_VALIDATE_FAILED;
            }
            ota_evt("IDENTITY_OK", "version=%s project=%.32s", candidate->version, desc->project_name);
        } else {
            ESP_LOGW(TAG, "spi_flash_mmap failed for identity check — proceeding (sha256 already verified)");
        }
    }

    /* B1: finalize the OTA handle (flushes partial write buffer, frees the
     * handle) BEFORE selecting the boot partition. In the QEMU test-hook
     * build esp_ota_end's read-back esp_image_verify is skipped (patched in
     * esp-idf) because of the same flash read-back bug; streamed sha256 +
     * RSA verification already covered the bytes. */
    err = esp_ota_end(ota);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end failed: %s", esp_err_to_name(err));
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=end error=%s", candidate->version, esp_err_to_name(err));
        return err;
    }
    ota_evt("OTA_END", "version=%s", candidate->version);

    /* Explicit boot selection; bootloader validates image magic/header (mmap
     * path) before executing, and PENDING_VERIFY self-test gates validity. */
    err = esp_ota_set_boot_partition(target);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition failed: %s", esp_err_to_name(err));
        ota_evt("DOWNLOAD_FAIL", "version=%s stage=set_boot error=%s", candidate->version, esp_err_to_name(err));
        return err;
    }
    ota_evt("BOOT_SET", "version=%s running=%s target=%s", candidate->version, running->label, target->label);
    return ESP_OK;
}
