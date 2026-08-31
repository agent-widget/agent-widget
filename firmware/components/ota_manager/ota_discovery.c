#include "ota_discovery.h"

#include <string.h>

#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "ota_events.h"
#include "sdkconfig.h"

#if CONFIG_AGENT_WIDGET_PLATFORM_QEMU
#include "qemu_test_ca.h"
#else
#include "esp_crt_bundle.h"
#endif

static const char *TAG = "ota_discovery";

#define HTTP_BUF_CAP 8192

static esp_err_t http_get(const char *url, char *buf, size_t buf_cap, size_t *out_len)
{
    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = 15000,
        .disable_auto_redirect = false,
        .keep_alive_enable = true,
    };
#if CONFIG_AGENT_WIDGET_PLATFORM_QEMU
    config.cert_pem = QEMU_TEST_CA_PEM;
#else
    config.crt_bundle_attach = esp_crt_bundle_attach;
#endif

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        return ESP_FAIL;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "open %s failed: %s", url, esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return err;
    }

    esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        ESP_LOGW(TAG, "GET %s -> HTTP %d", url, status);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }

    size_t total = 0;
    while (total < buf_cap - 1) {
        int r = esp_http_client_read(client, buf + total, buf_cap - 1 - total);
        if (r < 0) {
            err = ESP_FAIL;
            break;
        }
        if (r == 0) {
            break;
        }
        total += (size_t)r;
    }
    buf[total] = '\0';
    *out_len = total;

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return err;
}

static bool extract_release_version(const char *json, size_t len, char *out, size_t out_len)
{
    cJSON *root = cJSON_ParseWithLength(json, len);
    if (root == NULL) {
        return false;
    }
    const cJSON *tag = cJSON_GetObjectItemCaseSensitive(root, "tag_name");
    bool ok = false;
    if (cJSON_IsString(tag) && tag->valuestring != NULL) {
        const char *v = tag->valuestring;
        if (v[0] == 'v' || v[0] == 'V') {
            v++;
        }
        if (strlen(v) < out_len) {
            strlcpy(out, v, out_len);
            ok = true;
        }
    }
    cJSON_Delete(root);
    return ok;
}

esp_err_t ota_discovery_check(const ota_discovery_config_t *cfg, const char *running_version,
                               ota_manifest_record_t *out)
{
    static char buf[HTTP_BUF_CAP];
    size_t len = 0;
    char release_version[OTA_MANIFEST_MAX_VERSION_LEN] = {0};

    bool have_release = false;
    if (http_get(cfg->releases_api_url, buf, sizeof(buf), &len) == ESP_OK &&
        extract_release_version(buf, len, release_version, sizeof(release_version))) {
        have_release = true;
        ota_evt("CHANNEL_RESULT", "channel=releases_api result=OK version=%s", release_version);
    } else {
        ota_evt("CHANNEL_RESULT", "channel=releases_api result=FAIL");
    }

    if (http_get(cfg->manifest_url, buf, sizeof(buf), &len) != ESP_OK) {
        ota_evt("CHANNEL_RESULT", "channel=manifest result=FAIL");
        /* Manifest unavailable => no trusted candidate, even if the API succeeded. */
        return ESP_FAIL;
    }
    ota_evt("CHANNEL_RESULT", "channel=manifest result=OK bytes=%u", (unsigned)len);

    static ota_manifest_record_t records[8];
    size_t count = 0;
    if (ota_manifest_parse(buf, len, records, 8, &count) != ESP_OK || count == 0) {
        ota_evt("CANDIDATE", "result=NONE reason=manifest_unparseable");
        return ESP_FAIL;
    }

    const ota_manifest_record_t *rec = NULL;
    if (have_release) {
        rec = ota_manifest_find(records, count, release_version);
        if (rec == NULL) {
            ota_evt("CANDIDATE", "result=NONE reason=releases_manifest_mismatch releases_version=%s",
                    release_version);
            return ESP_ERR_NOT_FOUND;
        }
    } else {
        /* API unavailable: the manifest alone is the fallback (its newest entry). */
        for (size_t i = 0; i < count; i++) {
            if (rec == NULL || ota_manifest_version_gt(records[i].version, rec->version)) {
                rec = &records[i];
            }
        }
    }

    if (!ota_manifest_version_gt(rec->version, running_version)) {
        ota_evt("CANDIDATE", "result=NONE reason=not_newer candidate=%s running=%s", rec->version, running_version);
        return ESP_ERR_NOT_FOUND;
    }
    if (!ota_manifest_version_ge(running_version, rec->min_version)) {
        ota_evt("CANDIDATE", "result=NONE reason=below_min_version candidate=%s min=%s running=%s",
                rec->version, rec->min_version, running_version);
        return ESP_ERR_NOT_FOUND;
    }

    *out = *rec;
    ota_evt("CANDIDATE", "version=%s size=%u", rec->version, (unsigned)rec->size);
    return ESP_OK;
}
