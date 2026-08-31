#include "ota_manifest.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_log.h"
#include "mbedtls/base64.h"

static const char *TAG = "ota_manifest";

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool hex_decode_32(const char *hex, size_t hex_len, uint8_t out[32])
{
    if (hex_len != 64) {
        return false;
    }
    for (int i = 0; i < 32; i++) {
        int hi = hex_nibble(hex[i * 2]);
        int lo = hex_nibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return true;
}

static bool parse_version_triple(const char *v, int *maj, int *min, int *patch)
{
    if (v == NULL) return false;
    return sscanf(v, "%d.%d.%d", maj, min, patch) == 3;
}

bool ota_manifest_version_gt(const char *a, const char *b)
{
    int a1, a2, a3, b1, b2, b3;
    if (!parse_version_triple(a, &a1, &a2, &a3) || !parse_version_triple(b, &b1, &b2, &b3)) {
        return false;
    }
    if (a1 != b1) return a1 > b1;
    if (a2 != b2) return a2 > b2;
    return a3 > b3;
}

bool ota_manifest_version_eq(const char *a, const char *b)
{
    int a1, a2, a3, b1, b2, b3;
    if (!parse_version_triple(a, &a1, &a2, &a3) || !parse_version_triple(b, &b1, &b2, &b3)) {
        return false;
    }
    return a1 == b1 && a2 == b2 && a3 == b3;
}

bool ota_manifest_version_ge(const char *a, const char *b)
{
    return ota_manifest_version_gt(a, b) || ota_manifest_version_eq(a, b);
}

static bool get_string_field(const cJSON *obj, const char *key, char *out, size_t out_len)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsString(item) || item->valuestring == NULL) {
        return false;
    }
    size_t src_len = strlen(item->valuestring);
    if (src_len >= out_len) {
        return false;
    }
    memcpy(out, item->valuestring, src_len + 1);
    return true;
}

static bool parse_one_record(const cJSON *item, ota_manifest_record_t *rec)
{
    memset(rec, 0, sizeof(*rec));

    const cJSON *schema_version = cJSON_GetObjectItemCaseSensitive(item, "schema_version");
    if (schema_version != NULL && cJSON_IsNumber(schema_version) && schema_version->valueint != 1) {
        ESP_LOGW(TAG, "skipping record: unsupported schema_version=%d", schema_version->valueint);
        return false;
    }

    if (!get_string_field(item, "version", rec->version, sizeof(rec->version))) {
        ESP_LOGW(TAG, "skipping record: missing/oversized version");
        return false;
    }
    if (!get_string_field(item, "url", rec->url, sizeof(rec->url))) {
        ESP_LOGW(TAG, "skipping record %s: missing/oversized url", rec->version);
        return false;
    }
    if (strncmp(rec->url, "https://", 8) != 0) {
        ESP_LOGW(TAG, "skipping record %s: non-HTTPS url", rec->version);
        return false;
    }

    const cJSON *size_item = cJSON_GetObjectItemCaseSensitive(item, "size");
    if (!cJSON_IsNumber(size_item) || size_item->valuedouble <= 0) {
        ESP_LOGW(TAG, "skipping record %s: missing/invalid size", rec->version);
        return false;
    }
    rec->size = (uint32_t)size_item->valuedouble;

    char sha_hex[65] = {0};
    if (!get_string_field(item, "sha256", sha_hex, sizeof(sha_hex)) ||
        !hex_decode_32(sha_hex, strlen(sha_hex), rec->sha256)) {
        ESP_LOGW(TAG, "skipping record %s: invalid sha256", rec->version);
        return false;
    }

    char sig_b64[400] = {0};
    if (!get_string_field(item, "signature", sig_b64, sizeof(sig_b64))) {
        ESP_LOGW(TAG, "skipping record %s: missing signature", rec->version);
        return false;
    }
    size_t sig_olen = 0;
    int mret = mbedtls_base64_decode(rec->signature, sizeof(rec->signature), &sig_olen,
                                      (const unsigned char *)sig_b64, strlen(sig_b64));
    if (mret != 0 || sig_olen != OTA_MANIFEST_SIGNATURE_LEN) {
        ESP_LOGW(TAG, "skipping record %s: invalid signature encoding/length (%d, %u)",
                 rec->version, mret, (unsigned)sig_olen);
        return false;
    }
    rec->signature_len = sig_olen;

    /* min_version is optional; default to 0.0.0 (no constraint). */
    if (!get_string_field(item, "min_version", rec->min_version, sizeof(rec->min_version))) {
        strlcpy(rec->min_version, "0.0.0", sizeof(rec->min_version));
    }

    return true;
}

esp_err_t ota_manifest_parse(const char *json, size_t len,
                              ota_manifest_record_t *out_records, size_t max_records,
                              size_t *out_count)
{
    if (json == NULL || out_records == NULL || out_count == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out_count = 0;

    cJSON *root = cJSON_ParseWithLength(json, len);
    if (root == NULL) {
        ESP_LOGE(TAG, "manifest JSON parse failed");
        return ESP_ERR_INVALID_ARG;
    }

    const cJSON *releases = cJSON_GetObjectItemCaseSensitive(root, "releases");
    if (!cJSON_IsArray(releases)) {
        ESP_LOGE(TAG, "manifest missing 'releases' array");
        cJSON_Delete(root);
        return ESP_ERR_INVALID_ARG;
    }

    size_t count = 0;
    const cJSON *item = NULL;
    cJSON_ArrayForEach(item, releases)
    {
        if (count >= max_records) {
            break;
        }
        if (parse_one_record(item, &out_records[count])) {
            count++;
        }
    }

    cJSON_Delete(root);
    *out_count = count;
    return ESP_OK;
}

const ota_manifest_record_t *ota_manifest_find(const ota_manifest_record_t *records, size_t count,
                                                const char *version)
{
    for (size_t i = 0; i < count; i++) {
        if (ota_manifest_version_eq(records[i].version, version)) {
            return &records[i];
        }
    }
    return NULL;
}
