/*
 * Agent Widget — GitHub OTA 客户端（Wokwi 模拟验证，版本感知，AW-006 完整产品体验）
 *
 * 编译时注入（由 build_arduino.sh / run_ota_ui.js 替换）：
 *   FW_VERSION            当前固件版本，如 "1.0.0"
 *   OTA_TARGET_VERSION    "latest" = 自动升级到 GitHub 上最新版；
 *                          或 "x.y.z" = 指定升级到任意已发布版本（设置入口的模拟）
 *   CHECK_INTERVAL_MS     周期检查间隔（默认 3600000 = 1h；测试用短间隔如 30000）
 *   SELFTEST_FORCE_FAIL   1 = 启动自检强制失败（破坏性测试 #4 专用构建变体）
 *
 * 固件源（双通道，AW-006 起始终合并查询，而非"A 失败才查 B"）：
 *   A. GitHub Releases API — 提供权威下载 URL（生产主通道）
 *   B. manifest.json       — 提供每个版本的 sha256 + signature 完整性元数据
 *      （Releases API 的 asset 没有自定义字段存放位置，因此完整性元数据统一放在
 *       manifest.json，无论固件字节实际由哪个通道提供 —— 见 docs.local/operations
 *       报告 "关键决策" 和 docs/ota/10。这是对 brief 字面描述的必要延伸。）
 *
 * 流程：启动 → 自检（core 内置 rollback hook，见 verifyOta()）→ 连 Wokwi-GUEST →
 *       周期/手动检查 → 发现新版 → UI+串口提示 → 用户按键/串口 'u' 确认 →
 *       下载并边写边算 sha256 → sha256 比对 → RSA-2048 PKCS#1v1.5 验签 → 全部通过
 *       才 Update.end(true) 重启；任一失败 Update.abort()，旧固件继续运行。
 */
#ifndef FW_VERSION
#define FW_VERSION "1.0.0"
#endif
#ifndef OTA_TARGET_VERSION
#define OTA_TARGET_VERSION "latest"
#endif
#ifndef CHECK_INTERVAL_MS
#define CHECK_INTERVAL_MS 3600000UL
#endif
#ifndef SELFTEST_FORCE_FAIL
#define SELFTEST_FORCE_FAIL 0
#endif

#define GITHUB_OWNER "agent-widget"
#define GITHUB_REPO  "agent-widget"
#define GITHUB_BRANCH "main"
#define RELEASES_API_URL "https://api.github.com/repos/agent-widget/agent-widget/releases"
#define MANIFEST_URL "https://raw.githubusercontent.com/agent-widget/agent-widget/main/firmware/manifest.json"

#define BUTTON_PIN 27

/* ---------------- ILI9341 UI（TFT_eSPI，内联配置，不改库文件） ---------------- */
#define USER_SETUP_LOADED
#define ILI9341_DRIVER
#define TFT_MISO 19
#define TFT_MOSI 23
#define TFT_SCLK 18
#define TFT_CS    5
#define TFT_DC    4
#define TFT_RST   2
#define LOAD_GLCD
#define SPI_FREQUENCY 20000000

#include <WiFi.h>
#include <HTTPClient.h>
#include <Update.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include "esp_ota_ops.h"
#include "mbedtls/sha256.h"
#include "mbedtls/rsa.h"
#include "mbedtls/base64.h"
#include "ota_pubkey.h"

TFT_eSPI tft = TFT_eSPI();

typedef struct {
  String version;
  String url;
  String sha256;     // 十六进制小写，来自 manifest.json；Releases API 通道无此字段
  String signature;   // base64，来自 manifest.json
} fw_entry_t;

typedef enum {
  ST_IDLE = 0,
  ST_CHECKING,
  ST_AVAILABLE,
  ST_DOWNLOADING,
  ST_VERIFYING,
  ST_APPLYING,
  ST_SUCCESS,
  ST_FAILED
} ota_state_t;

static ota_state_t g_state = ST_IDLE;
static fw_entry_t g_pending;                 // 当前待确认/正在处理的目标版本
static unsigned long g_lastCheckMs = 0;
static bool g_lastButton = HIGH;
static unsigned long g_lastButtonMs = 0;

/* ================================================================
 * semver 比较（既有逻辑，不改）
 * ================================================================ */
static int ver_cmp(const String &a, const String &b) {
  int pa = 0, pb = 0;
  while (true) {
    int ea = a.indexOf('.', pa);
    int eb = b.indexOf('.', pb);
    String sa = (ea < 0) ? a.substring(pa) : a.substring(pa, ea);
    String sb = (eb < 0) ? b.substring(pb) : b.substring(pb, eb);
    int na = sa.toInt(), nb = sb.toInt();
    if (na != nb) return (na > nb) ? 1 : -1;
    if (ea < 0 && eb < 0) return 0;
    if (ea < 0) return -1;             // "1.0" < "1.0.1"
    if (eb < 0) return 1;              // "1.0.1" > "1.0"
    pa = ea + 1; pb = eb + 1;
  }
}

/* ================================================================
 * HTTP GET（既有逻辑，不改）
 * ================================================================ */
static int http_get_string(const char *url, String &out, long maxLen) {
  HTTPClient http;
  http.setConnectTimeout(15000);
  http.setTimeout(30000);
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  http.setUserAgent("agent-widget-ota/1.0");
  if (!http.begin(url)) {
    http.end();
    return -1;
  }
  int code = http.GET();
  if (code == HTTP_CODE_OK) {
    long size = http.getSize();
    if (size > maxLen) {
      Serial.printf("[OTA] Response too large: %ld > %ld bytes\n", size, maxLen);
      http.end();
      return -2;
    }
    out = http.getString();
  }
  http.end();
  return code;
}

/* ================================================================
 * 极简 JSON 解析（既有逻辑 + AW-006 扩展：有界查找，避免读到下一条 entry）
 * ================================================================ */
static int find_key_value(const String &json, const char *key, int from, String &out, int upto = -1) {
  String pat = String("\"") + key + "\"";
  int p = json.indexOf(pat, from);
  if (p < 0) return -1;
  if (upto >= 0 && p >= upto) return -1;
  int i = p + pat.length();
  while (i < (int)json.length() && (json[i] == ' ' || json[i] == '\t' || json[i] == '\r' || json[i] == '\n')) i++;
  if (i >= (int)json.length() || json[i] != ':') return -1;
  i++;
  while (i < (int)json.length() && (json[i] == ' ' || json[i] == '\t' || json[i] == '\r' || json[i] == '\n')) i++;
  if (i >= (int)json.length() || json[i] != '"') return -1;
  i++;
  int e = json.indexOf('"', i);
  if (e < 0) return -1;
  out = json.substring(i, e);
  return e + 1;
}

/* Releases API: [{...,"tag_name":"v2.0.0",...,"assets":[{...,"browser_download_url":"https://..."}}] */
static bool parse_releases_api(const String &json, fw_entry_t *out, int max) {
  int n = 0, pos = 0;
  while (n < max) {
    String tag;
    int tp = find_key_value(json, "tag_name", pos, tag);
    if (tp < 0) break;
    if (tag.startsWith("v")) tag = tag.substring(1);
    String url;
    int up = find_key_value(json, "browser_download_url", tp, url);
    if (up < 0) break;
    out[n].version = tag;
    out[n].url = url;
    n++; pos = up;
  }
  return n > 0;
}

/* manifest.json: [{"version":"2.0.0","url":"...","size":...,"sha256":"...","signature":"..."}, ...]
 * sha256/signature 可选：老条目/无 sig 的测试用例可能没有。 */
static bool parse_manifest(const String &json, fw_entry_t *out, int max) {
  int n = 0, pos = 0;
  while (n < max) {
    String ver;
    int vp = find_key_value(json, "version", pos, ver);
    if (vp < 0) break;
    String url;
    int up = find_key_value(json, "url", vp, url);
    if (up < 0) break;
    int nextEntry = json.indexOf("\"version\"", up);
    int boundary = (nextEntry < 0) ? json.length() : nextEntry;
    String sha, sig;
    find_key_value(json, "sha256", up, sha, boundary);
    find_key_value(json, "signature", up, sig, boundary);
    out[n].version = ver;
    out[n].url = url;
    out[n].sha256 = sha;
    out[n].signature = sig;
    n++; pos = boundary;
  }
  return n > 0;
}

/* ================================================================
 * 通道合并：manifest 提供完整性元数据基线，Releases API 覆盖 URL（若存在）
 * ================================================================ */
static int merge_channels(fw_entry_t *a, int na, fw_entry_t *b, int nb, fw_entry_t *out, int max) {
  int n = 0;
  for (int i = 0; i < nb && n < max; i++) {
    out[n++] = b[i];
  }
  for (int i = 0; i < na; i++) {
    int found = -1;
    for (int j = 0; j < n; j++) if (out[j].version == a[i].version) { found = j; break; }
    if (found >= 0) {
      out[found].url = a[i].url;  // 优先官方 Releases 资产 URL
    } else if (n < max) {
      out[n].version = a[i].version;
      out[n].url = a[i].url;
      out[n].sha256 = "";
      out[n].signature = "";
      n++;
    }
  }
  return n;
}

/* ---------------- 目标选择（既有逻辑，不改） ---------------- */
static bool pick_target(fw_entry_t *fw, int n, const String &target, fw_entry_t &outEntry) {
  if (n <= 0) return false;
  if (target == "latest") {
    int best = 0;
    for (int i = 1; i < n; i++)
      if (ver_cmp(fw[i].version, fw[best].version) > 0) best = i;
    outEntry = fw[best];
    return true;
  }
  for (int i = 0; i < n; i++)
    if (fw[i].version == target) {
      outEntry = fw[i];
      return true;
    }
  return false;
}

/* ================================================================
 * UI（ILI9341，英文文案：TFT_eSPI 默认字体不含中文字形，
 *     avoid mojibake — see docs.local report "key decision"）
 * ================================================================ */
static void ui_init() {
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.setCursor(4, 4);
  tft.println("Agent Widget OTA");
  tft.setTextSize(1);
  tft.setCursor(4, 26);
  tft.printf("FW v%s\n", FW_VERSION);
}

static void ui_frame(const char *title, uint16_t titleColor) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(titleColor, TFT_BLACK);
  tft.setTextSize(2);
  tft.setCursor(4, 4);
  tft.println(title);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(1);
}

static void ui_show_available() {
  ui_frame("New firmware!", TFT_YELLOW);
  tft.setCursor(4, 40);
  tft.printf("v%s available\n", g_pending.version.c_str());
  tft.setCursor(4, 56);
  tft.printf("(current v%s)\n", FW_VERSION);
  tft.setCursor(4, 80);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.println("Press BUTTON to upgrade");
  tft.setCursor(4, 96);
  tft.println("(or serial 'u')");
}

static void ui_show_downloading(int pct) {
  ui_frame("Downloading...", TFT_ORANGE);
  tft.setCursor(4, 40);
  tft.printf("v%s\n", g_pending.version.c_str());
  tft.fillRect(4, 60, 220, 16, TFT_DARKGREY);
  tft.fillRect(4, 60, (int)(220.0 * pct / 100.0), 16, TFT_ORANGE);
  tft.setCursor(4, 80);
  tft.printf("%d%%\n", pct);
}

static void ui_show_verifying() {
  ui_frame("Verifying...", TFT_ORANGE);
  tft.setCursor(4, 40);
  tft.println("sha256 + RSA signature");
}

static void ui_show_success() {
  ui_frame("OTA SUCCESS", TFT_GREEN);
  tft.setCursor(4, 40);
  tft.printf("Now running v%s\n", g_pending.version.c_str());
  tft.setCursor(4, 56);
  tft.println("Rebooting...");
}

static void ui_show_failed(const char *reason) {
  ui_frame("OTA REJECTED", TFT_RED);
  tft.setCursor(4, 40);
  tft.println(reason);
  tft.setCursor(4, 64);
  tft.printf("Still on v%s\n", FW_VERSION);
}

static void ui_show_idle() {
  ui_frame("Agent Widget", TFT_WHITE);
  tft.setCursor(4, 40);
  tft.printf("FW v%s\n", FW_VERSION);
  tft.setCursor(4, 56);
  tft.println("Up to date");
}

/* ================================================================
 * sha256 / RSA 验签
 * ================================================================ */
static void bytes_to_hex(const uint8_t *b, size_t n, String &out) {
  static const char *hexd = "0123456789abcdef";
  out = "";
  for (size_t i = 0; i < n; i++) {
    out += hexd[(b[i] >> 4) & 0xF];
    out += hexd[b[i] & 0xF];
  }
}

static bool rsa_verify_sha256(const uint8_t digest[32], const uint8_t *sig, size_t sigLen) {
  mbedtls_rsa_context rsa;
  mbedtls_rsa_init(&rsa);
  bool ok = false;
  do {
    if (mbedtls_rsa_import_raw(&rsa, OTA_PUBKEY_N, sizeof(OTA_PUBKEY_N), NULL, 0, NULL, 0, NULL, 0,
                                OTA_PUBKEY_E, sizeof(OTA_PUBKEY_E)) != 0) break;
    if (mbedtls_rsa_complete(&rsa) != 0) break;
    if (mbedtls_rsa_set_padding(&rsa, MBEDTLS_RSA_PKCS_V15, MBEDTLS_MD_SHA256) != 0) break;
    if (sigLen != mbedtls_rsa_get_len(&rsa)) break;
    ok = (mbedtls_rsa_pkcs1_verify(&rsa, MBEDTLS_MD_SHA256, 32, digest, sig) == 0);
  } while (0);
  mbedtls_rsa_free(&rsa);
  return ok;
}

/* ================================================================
 * OTA 下载 + 边写边算 sha256 + 校验 + 验签（AW-006 核心）
 * ================================================================ */
static void perform_ota_verified() {
  const String url = g_pending.url;
  Serial.print("[OTA] Downloading new firmware from: ");
  Serial.println(url);

  HTTPClient http;
  http.setConnectTimeout(15000);
  http.setTimeout(60000);
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  http.setUserAgent("agent-widget-ota/1.0");
  if (!http.begin(url)) {
    Serial.println("[OTA] http.begin() FAILED");
    g_state = ST_FAILED;
    ui_show_failed("http begin failed");
    return;
  }
  int code = http.GET();
  Serial.printf("[OTA] HTTP GET response code: %d\n", code);
  if (code != HTTP_CODE_OK) {
    Serial.printf("[OTA] FAILED: HTTP code %d (expected 200)\n", code);
    http.end();
    g_state = ST_FAILED;
    ui_show_failed("download http error");
    return;
  }
  int total = http.getSize();
  Serial.printf("[OTA] Firmware size: %d bytes\n", total);

  if (!Update.begin(total)) {
    Serial.print("[OTA] Update.begin() FAILED: ");
    Update.printError(Serial);
    http.end();
    g_state = ST_FAILED;
    ui_show_failed("Update.begin failed");
    return;
  }
  Serial.println("[OTA] Update.begin() OK, writing to (inactive) OTA slot ...");

  mbedtls_sha256_context sctx;
  mbedtls_sha256_init(&sctx);
  mbedtls_sha256_starts(&sctx, 0);

  WiFiClient *stream = http.getStreamPtr();
  uint8_t buf[1024];
  int written = 0, lastPct = -1;
  while (http.connected() && (total <= 0 || written < total)) {
    size_t avail = stream->available();
    if (avail) {
      size_t n = stream->readBytes(buf, (avail > sizeof(buf)) ? sizeof(buf) : avail);
      if (Update.write(buf, n) != n) {
        Serial.print("[OTA] Update.write() FAILED: ");
        Update.printError(Serial);
        Update.abort();
        mbedtls_sha256_free(&sctx);
        http.end();
        g_state = ST_FAILED;
        ui_show_failed("flash write failed");
        return;
      }
      mbedtls_sha256_update(&sctx, buf, n);
      written += n;
      if (total > 0) {
        int pct = (int)((long)written * 100 / total);
        if (pct / 10 != lastPct / 10) {
          Serial.printf("[OTA] Progress: %d%% (%d / %d bytes)\n", pct, written, total);
          ui_show_downloading(pct);
          lastPct = pct;
        }
      }
    }
    delay(1);
  }
  http.end();
  Serial.printf("[OTA] Downloaded %d bytes (expected %d)\n", written, total);

  if (total > 0 && written != total) {
    Serial.println("[OTA] FAILED: incomplete download (connection dropped mid-transfer)");
    Update.abort();
    mbedtls_sha256_free(&sctx);
    g_state = ST_FAILED;
    ui_show_failed("incomplete download");
    return;
  }

  g_state = ST_VERIFYING;
  ui_show_verifying();

  uint8_t digest[32];
  mbedtls_sha256_finish(&sctx, digest);
  mbedtls_sha256_free(&sctx);
  String digestHex;
  bytes_to_hex(digest, 32, digestHex);
  Serial.print("[OTA] Computed sha256:  ");
  Serial.println(digestHex);
  Serial.print("[OTA] Manifest sha256:  ");
  Serial.println(g_pending.sha256.length() ? g_pending.sha256 : "(missing)");

  if (g_pending.sha256.length() == 0) {
    Serial.println("[OTA] REJECTED: no sha256 declared for this version — refusing to install");
    Update.abort();
    g_state = ST_FAILED;
    ui_show_failed("no sha256 metadata");
    return;
  }
  String wantSha = g_pending.sha256;
  wantSha.toLowerCase();
  if (!digestHex.equalsIgnoreCase(wantSha)) {
    Serial.println("[OTA] REJECTED: sha256 MISMATCH — firmware corrupt or tampered, not writing boot pointer");
    Update.abort();
    g_state = ST_FAILED;
    ui_show_failed("sha256 mismatch");
    return;
  }
  Serial.println("[OTA] sha256 OK");

  if (g_pending.signature.length() == 0) {
    Serial.println("[OTA] REJECTED: no signature declared for this version — refusing to install");
    Update.abort();
    g_state = ST_FAILED;
    ui_show_failed("no signature metadata");
    return;
  }
  uint8_t sigBuf[256];
  size_t sigLen = 0;
  int b64rc = mbedtls_base64_decode(sigBuf, sizeof(sigBuf), &sigLen,
                                     (const unsigned char *)g_pending.signature.c_str(),
                                     g_pending.signature.length());
  if (b64rc != 0) {
    Serial.printf("[OTA] REJECTED: signature is not valid base64 (rc=%d)\n", b64rc);
    Update.abort();
    g_state = ST_FAILED;
    ui_show_failed("bad signature encoding");
    return;
  }
  if (!rsa_verify_sha256(digest, sigBuf, sigLen)) {
    Serial.println("[OTA] REJECTED: RSA signature INVALID — firmware not from a trusted publisher, not writing boot pointer");
    Update.abort();
    g_state = ST_FAILED;
    ui_show_failed("signature invalid");
    return;
  }
  Serial.println("[OTA] RSA signature OK — publisher identity verified");

  g_state = ST_APPLYING;
  if (Update.end(true)) {
    Serial.printf("[OTA] Update SUCCESS! %d bytes written, sha256+signature verified.\n", written);
    Serial.printf("[OTA] New boot partition set. Now running target v%s after reboot.\n", g_pending.version.c_str());
    g_state = ST_SUCCESS;
    ui_show_success();
    Serial.println();
    delay(800);
    ESP.restart();
  } else {
    Serial.print("[OTA] Update.end() FAILED: ");
    Update.printError(Serial);
    g_state = ST_FAILED;
    ui_show_failed("Update.end failed");
  }
}

/* ================================================================
 * 检查更新（合并双通道 + 状态机，不阻塞）
 * ================================================================ */
static void begin_check() {
  g_state = ST_CHECKING;
  fw_entry_t fwA[8], fwB[8], merged[8];
  int nA = 0, nB = 0;

  String json;
  int code = http_get_string(RELEASES_API_URL, json, 65536);
  if (code == HTTP_CODE_OK && parse_releases_api(json, fwA, 8)) {
    nA = 8;
    Serial.println("[OTA] Channel A (Releases API): OK");
  } else {
    Serial.printf("[OTA] Channel A (Releases API): unavailable (code=%d)\n", code);
  }

  String m;
  int mcode = http_get_string(MANIFEST_URL, m, 16384);
  if (mcode == HTTP_CODE_OK && parse_manifest(m, fwB, 8)) {
    nB = 8;
    Serial.println("[OTA] Channel B (manifest.json): OK");
  } else {
    Serial.printf("[OTA] Channel B (manifest.json): unavailable (code=%d)\n", mcode);
  }

  int n = merge_channels(fwA, nA, fwB, nB, merged, 8);
  if (n <= 0) {
    Serial.println("[OTA] No firmware source reachable this check — OTA unavailable");
    g_state = ST_IDLE;
    return;
  }

  Serial.printf("[OTA] Available versions (%d):", n);
  for (int i = 0; i < n; i++) Serial.printf(" %s", merged[i].version.c_str());
  Serial.println();

  fw_entry_t chosen;
  if (!pick_target(merged, n, OTA_TARGET_VERSION, chosen)) {
    Serial.printf("[OTA] Target '%s' not found in available releases\n", OTA_TARGET_VERSION);
    g_state = ST_IDLE;
    return;
  }
  int c = ver_cmp(chosen.version, FW_VERSION);
  if (c <= 0) {
    Serial.printf("[OTA] Current %s already >= target %s. No update needed.\n", FW_VERSION, chosen.version.c_str());
    g_state = ST_IDLE;
    ui_show_idle();
    return;
  }

  g_pending = chosen;
  g_state = ST_AVAILABLE;
  Serial.printf("[OTA] UPDATE AVAILABLE: v%s (current v%s) — press BUTTON or send 'u' over serial to confirm\n",
                chosen.version.c_str(), FW_VERSION);
  ui_show_available();
}

static void confirm_upgrade() {
  if (g_state != ST_AVAILABLE) {
    Serial.println("[OTA] confirm ignored: no pending update");
    return;
  }
  Serial.println("[OTA] User CONFIRMED upgrade.");
  g_state = ST_DOWNLOADING;
  ui_show_downloading(0);
  perform_ota_verified();
}

/* ================================================================
 * 启动自检 + 回滚（用 arduino-esp32 core 内置 rollback hook，见
 * esp32-hal-misc.c: initArduino() 在 setup() 之前检测
 * ESP_OTA_IMG_PENDING_VERIFY 状态并调用 verifyOta()；
 * CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE 在这个 esp32 core 里默认开启，
 * 不需要额外配置。verifyOta() 早于 setup() 执行，Serial 可能还没
 * begin，这里显式 begin 一次（HardwareSerial 允许重复 begin）。
 * ================================================================ */
bool verifyOta() {
  Serial.begin(115200);
  delay(50);
  Serial.println();
  Serial.println("[SELFTEST] post-OTA self-test starting ...");
#if SELFTEST_FORCE_FAIL
  Serial.println("[SELFTEST] FORCED FAILURE (this build variant is a rollback drill)");
  return false;
#else
  Serial.print("[SELFTEST] connecting to Wokwi-GUEST to verify network stack");
  WiFi.begin("Wokwi-GUEST", "", 6);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    Serial.print(".");
    delay(200);
  }
  Serial.println();
  bool ok = (WiFi.status() == WL_CONNECTED);
  Serial.printf("[SELFTEST] wifi_connected=%d -> %s\n", ok, ok ? "PASS" : "FAIL");
  return ok;
#endif
}

/* ---------------- WiFi（既有逻辑，不改） ---------------- */
static void connect_wifi() {
  if (WiFi.status() == WL_CONNECTED) return;  // verifyOta() may have already connected it
  Serial.print("[WIFI] Connecting to Wokwi-GUEST");
  WiFi.begin("Wokwi-GUEST", "", 6);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 150) {
    Serial.print(".");
    delay(100);
    tries++;
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WIFI] Connected! Local IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WIFI] FAILED to connect (retrying in loop)");
  }
}

/* ---------------- 主流程 ---------------- */
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("==============================================");
  Serial.print("[BOOT] Firmware VERSION : ");
  Serial.println(FW_VERSION);
  Serial.print("[BOOT] OTA target       : ");
  Serial.println(OTA_TARGET_VERSION);
  Serial.print("[BOOT] Check interval   : ");
  Serial.print(CHECK_INTERVAL_MS);
  Serial.println(" ms");
  Serial.println("==============================================");

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  ui_init();

  connect_wifi();
  begin_check();
  g_lastCheckMs = millis();
}

void loop() {
  // 串口命令：c = 立即检查，u = 确认升级
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'c' || c == 'C') {
      Serial.println("[OTA] Manual check requested (serial 'c')");
      g_lastCheckMs = millis();
      begin_check();
    } else if (c == 'u' || c == 'U') {
      confirm_upgrade();
    }
  }

  // 按键（下降沿，50ms 消抖）：确认升级
  bool btn = digitalRead(BUTTON_PIN);
  if (g_lastButton == HIGH && btn == LOW && (millis() - g_lastButtonMs) > 50) {
    g_lastButtonMs = millis();
    Serial.println("[OTA] Button pressed");
    confirm_upgrade();
  }
  g_lastButton = btn;

  // 周期检查（非阻塞）
  if (g_state == ST_IDLE && (millis() - g_lastCheckMs) >= CHECK_INTERVAL_MS) {
    g_lastCheckMs = millis();
    Serial.println("[OTA] Periodic check triggered");
    begin_check();
  }

  if (g_state == ST_IDLE || g_state == ST_AVAILABLE) {
    static unsigned long lastBeat = 0;
    if (millis() - lastBeat > 5000) {
      lastBeat = millis();
      Serial.printf("[APP] heartbeat ... running firmware %s (state=%d)\n", FW_VERSION, (int)g_state);
    }
  }
  delay(5);
}
