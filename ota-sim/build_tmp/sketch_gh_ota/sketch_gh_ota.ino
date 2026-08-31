/*
 * Agent Widget — GitHub OTA 客户端（Wokwi 模拟验证，版本感知）
 *
 * 编译时注入（由 build_gh.py 替换）：
 *   FW_VERSION         当前固件版本，如 "1.0.0"
 *   OTA_TARGET_VERSION "latest" = 自动升级到 GitHub 上最新版；
 *                     或 "x.y.z" = 指定升级到任意已发布版本（设置入口的模拟）
 *
 * 固件源（双通道，按序尝试）：
 *   A. GitHub Releases API  — 生产主通道（对应 docs/ota/05 SafeGithubOTA 方向）
 *   B. manifest.json        — PoC 过渡通道（raw.githubusercontent，仓库内发布清单）
 *
 * 流程：启动 → 打印版本 → 连 Wokwi-GUEST → 查询 GitHub → 目标 > 当前 → 下载 → 写 flash → 重启
 */
#ifndef FW_VERSION
#define FW_VERSION "1.0.0"
#endif
#ifndef OTA_TARGET_VERSION
#define OTA_TARGET_VERSION "latest"
#endif

#define GITHUB_OWNER "agent-widget"
#define GITHUB_REPO  "agent-widget"
#define GITHUB_BRANCH "main"
#define RELEASES_API_URL "https://api.github.com/repos/agent-widget/agent-widget/releases"
#define MANIFEST_URL "https://raw.githubusercontent.com/agent-widget/agent-widget/main/firmware/manifest.json"

#include <WiFi.h>
#include <HTTPClient.h>
#include <Update.h>

typedef struct {
  String version;
  String url;
} fw_entry_t;

/* ---------------- semver 比较（MAJOR.MINOR.PATCH，整数段） ---------------- */
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

/* ---------------- HTTP GET（响应限长，防内存爆） ---------------- */
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

/* ---------------- 极简 JSON 解析（不引第三方库，容忍 "key" : "value" 空格） ---------------- */
/* 查找 "key" : "value"，返回 value 结束引号后的下标；失败返回 -1 */
static int find_key_value(const String &json, const char *key, int from, String &out) {
  String pat = String("\"") + key + "\"";
  int p = json.indexOf(pat, from);
  if (p < 0) return -1;
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

/* manifest.json: [{"version":"2.0.0","url":"...","size":...}, ...] */
static bool parse_manifest(const String &json, fw_entry_t *out, int max) {
  int n = 0, pos = 0;
  while (n < max) {
    String ver;
    int vp = find_key_value(json, "version", pos, ver);
    if (vp < 0) break;
    String url;
    int up = find_key_value(json, "url", vp, url);
    if (up < 0) break;
    out[n].version = ver;
    out[n].url = url;
    n++; pos = up;
  }
  return n > 0;
}

/* ---------------- 目标选择 ---------------- */
static bool pick_target(fw_entry_t *fw, int n, const String &target, String &outVer, String &outUrl) {
  if (n <= 0) return false;
  if (target == "latest") {
    int best = 0;
    for (int i = 1; i < n; i++)
      if (ver_cmp(fw[i].version, fw[best].version) > 0) best = i;
    outVer = fw[best].version;
    outUrl = fw[best].url;
    return true;
  }
  for (int i = 0; i < n; i++)
    if (fw[i].version == target) {
      outVer = fw[i].version;
      outUrl = fw[i].url;
      return true;
    }
  return false;
}

/* ---------------- OTA 下载 + 写 flash ---------------- */
static void perform_ota(const char *url) {
  Serial.print("[OTA] Downloading new firmware from: ");
  Serial.println(url);

  HTTPClient http;
  http.setConnectTimeout(15000);
  http.setTimeout(60000);
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  http.setUserAgent("agent-widget-ota/1.0");
  if (!http.begin(url)) {
    Serial.println("[OTA] http.begin() FAILED");
    return;
  }
  int code = http.GET();
  Serial.printf("[OTA] HTTP GET response code: %d\n", code);
  if (code != HTTP_CODE_OK) {
    Serial.printf("[OTA] FAILED: HTTP code %d (expected 200)\n", code);
    http.end();
    return;
  }
  int total = http.getSize();
  Serial.printf("[OTA] Firmware size: %d bytes\n", total);

  if (!Update.begin(total)) {
    Serial.print("[OTA] Update.begin() FAILED: ");
    Update.printError(Serial);
    http.end();
    return;
  }
  Serial.println("[OTA] Update.begin() OK, writing to flash ...");

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
        http.end();
        return;
      }
      written += n;
      if (total > 0) {
        int pct = (int)((long)written * 100 / total);
        if (pct / 10 != lastPct / 10) {
          Serial.printf("[OTA] Progress: %d%% (%d / %d bytes)\n", pct, written, total);
          lastPct = pct;
        }
      }
    }
    delay(1);
  }
  Serial.printf("[OTA] Downloaded %d bytes (expected %d)\n", written, total);
  if (Update.end(true)) {
    Serial.printf("[OTA] Update SUCCESS! %d bytes written to flash.\n", written);
    Serial.println("[OTA] Rebooting into new firmware ...");
    Serial.println();
    delay(500);
    ESP.restart();
  } else {
    Serial.print("[OTA] Update.end() FAILED: ");
    Update.printError(Serial);
  }
  http.end();
}

/* ---------------- 检查更新 ---------------- */
static void check_and_update() {
  fw_entry_t fw[8];
  String ver, url;
  int n = 0;
  bool haveList = false;

  // 通道 A: GitHub Releases API
  String json;
  int code = http_get_string(RELEASES_API_URL, json, 65536);
  if (code == HTTP_CODE_OK && parse_releases_api(json, fw, 8)) {
    Serial.println("[OTA] Channel: GitHub Releases API");
    n = 8; haveList = true;
  } else {
    if (code == HTTP_CODE_OK)
      Serial.println("[OTA] Releases API: no release assets found");
    else if (code >= 0)
      Serial.printf("[OTA] Releases API: HTTP %d\n", code);
    else
      Serial.println("[OTA] Releases API: unreachable");

    // 通道 B: manifest.json（raw.githubusercontent）
    String m;
    int mcode = http_get_string(MANIFEST_URL, m, 16384);
    if (mcode == HTTP_CODE_OK && parse_manifest(m, fw, 8)) {
      Serial.println("[OTA] Channel: manifest.json (raw.githubusercontent)");
      n = 8; haveList = true;
    } else {
      Serial.printf("[OTA] Manifest: HTTP %d — OTA unavailable this boot\n", mcode);
      return;
    }
  }

  Serial.printf("[OTA] Available versions (%d):", n);
  for (int i = 0; i < n; i++) Serial.printf(" %s", fw[i].version.c_str());
  Serial.println();

  if (!pick_target(fw, n, OTA_TARGET_VERSION, ver, url)) {
    Serial.printf("[OTA] Target '%s' not found in available releases\n", OTA_TARGET_VERSION);
    return;
  }
  int c = ver_cmp(ver, FW_VERSION);
  if (c <= 0) {
    Serial.printf("[OTA] Current %s already >= target %s. No update needed.\n", FW_VERSION, ver.c_str());
    return;
  }
  Serial.printf("[OTA] Target %s > current %s → updating\n", ver.c_str(), FW_VERSION);
  perform_ota(url.c_str());
}

/* ---------------- WiFi ---------------- */
static void connect_wifi() {
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
  Serial.println("==============================================");

  connect_wifi();
  check_and_update();
}

void loop() {
  Serial.printf("[APP] heartbeat ... running firmware %s\n", FW_VERSION);
  delay(5000);
}
