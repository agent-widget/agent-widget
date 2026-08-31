> English version: [03-ota-design-evaluation.md](./03-ota-design-evaluation.md)

# 03-OTA 设计方案高阶模型评估（deepseek-v4-pro）

> 日期: 2026-08-22
> 评估模型: deepseek-v4-pro
> 评估对象: 02-ota-design-esp-https-rollback.md

---

我们需要回答中文。需要评估 ESP32 OTA 设计方案。要指出 3-5 严重缺陷/风险排序，对 5 待评估问题逐一回答，最终结论可行否修改，补充遗漏关键点如分区表、回滚时序、安全、功耗等。

我们需要作为资深嵌入式固件架构师 ESP32 专家严格评估。需要仔细分析方案。注意硬件: Waveshare ESP32-S3-Touch-LCD-3.5B: ESP32-S3R8, 8MB PSRAM, 16MB Flash。用途 AI Agent Status display WiFi + WebSocket LVGL。开发期免烧录快速迭代; 生产期可靠防变砖。方案 esp_https_ota + 双分区 Rollback + Secure Boot v2。

需要发现缺陷。分区表: nvs 0x9000 size 0x6000, otadata 0xf000 size 0x2000, phy_init 0x11000 0x1000, factory 0x20000 0x400000, ota_0 0x420000 0x400000, ota_1 0x820000 0x400000, storage spiffs 0xc20000 0x3E0000. Check sizes and offsets. 16MB flash = 0x1000000. End of storage: 0xc20000 + 0x3E0000 = 0x1000000 exactly? 0xc20000 + 0x3e0000 = 0x1000000 yes. Good. But SPIFFS size 0x3E0000 = 4063232 bytes ~3.875 MiB. Okay.

Potential issue: phy_init partition? Usually phy_init size maybe 0x1000 okay. nvs size 24KB maybe okay but maybe too small if OTA resumption + WiFi? Could be fine. But OTA resumption uses NVS? esp_https_ota with ota_resumption maybe uses RTC? Need check. But okay.

Critical defect: No "ota_data_initial" or "otadata" must be data/ota? okay.

But they included factory plus two OTA app slots. In ESP-IDF with dual OTA partitions, factory is not used as OTA slot, but bootloader may select factory if otadata invalid? App can use factory as fallback. However partition table with factory app plus ota_0/ota_1 may not allow OTA update to factory? esp_ota_get_next_update_partition usually returns ota_0 or ota_1, not factory. They intend factory as "最后兜底" but how to jump back to factory? Is there a mechanism? There is esp_ota_set_boot_partition(esp_ota_get_factory_partition())? Factory partition type app subtype factory. Could boot factory via "factory reset" or if ota data invalid? Actually bootloader behavior: if otadata says ota seq valid, boots OTA app. If ota data invalid/corrupt, boots factory. To intentionally jump to factory, could call esp_ota_set_boot_partition(factory partition) then restart. But need code path. Not in described flow. Might be missing.

Need identify severe defects.

Possible severe:
1. Rollback timeout / watchdog confusion: "自检失败/超时 → 硬件 watchdog 复位 → bootloader 自动回滚到上一槽" But hardware watchdog reset alone does not mark app invalid. Need explicitly call esp_ota_mark_app_invalid_rollback_and_reboot() if self-check fails or timeout. If app crashes repeatedly before app can mark invalid, bootloader has rollback counter? Actually CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE and CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT? Let's recall. In ESP-IDF, rollback process: after OTA update bootloader sets new partition as PENDING_VERIFY and boots it. If app calls esp_ota_mark_app_valid_cancel_rollback() it becomes valid. If app calls esp_ota_mark_app_invalid_rollback_and_reboot() it marks invalid and reboots to previous. If app crashes/never marks, bootloader has a "rollback" mechanism? Actually "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE" and "CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT" seconds? Hmm. Let's recall: There is "rollback and anti-rollback" mechanism. Bootloader counts boot attempts? Let's verify.

ESP-IDF OTA rollback: After successful OTA, new firmware boots. It has a state PENDING_VERIFY. If no call to esp_ota_mark_app_valid_cancel_rollback, after reboot? Actually there is no automatic timeout in app? Bootloader has a rollback counter? The bootloader checks otadata. If the partition is in PENDING_VERIFY and "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE" is set, bootloader may attempt to boot it and monitor? I think the bootloader does not automatically revert just because app didn't call valid. There is "app rollback" via `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? The rollback timeout only applies to anti-rollback? Let's recall precise.

ESP-IDF OTA rollback: There are three functions:
- esp_ota_mark_app_valid_cancel_rollback()
- esp_ota_mark_app_invalid_rollback_and_reboot()

If new firmware boots and doesn't call valid, the next reboot (e.g., due to crash) bootloader sees PENDING_VERIFY? Actually `esp_ota_mark_app_valid_cancel_rollback` sets otadata to VALID. If not called, bootloader sees otadata state? Maybe otadata has "new app" pending; bootloader sets it to PENDING_VERIFY? Hmm.

I recall: Bootloader checks ota_data. The ota_state can be:
- Undefined (0xFFFFFFFF) for factory?
- New?
- Pending verify?
- Valid
- Invalid
- Abort?

The OTA data format has `ota_seq` and `ota_state`. When OTA update writes new image, it doesn't set state? The bootloader when booting a new image sets state to PENDING_VERIFY in otadata. If the app calls valid, state becomes VALID. If not, state remains PENDING_VERIFY. Next boot bootloader sees PENDING_VERIFY. What does bootloader do? It probably boots the same image again (since no invalid mark), unless the app has called invalid. There is no automatic rollback on crash unless the app calls invalid. However, "rollback timeout" maybe in bootloader: if `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` enabled, bootloader can monitor the app and revert if no valid after timeout? Let's google memory: There is `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` where timeout is seconds. In `bootloader_flash.c`, after booting OTA app, if rollback enabled, bootloader sets a timer? Actually no, bootloader doesn't run alongside app. But there is a hardware RTC watchdog? Hmm.

Let's recall from docs: "Rollback Process" in ESP-IDF. The bootloader uses `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` to enable rollback support. If it is enabled, after OTA update and reboot, the new firmware is in PENDING_VERIFY state. The application must call `esp_ota_mark_app_valid_cancel_rollback()` to indicate it is valid. If the application fails to call this and reboots, the bootloader will mark the application invalid and roll back? Or if the application doesn't call in time? There is "rollback timeout" maybe `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` used by bootloader to wait for valid? Not possible because bootloader not running. Wait maybe app's `esp_ota_mark_app_valid_cancel_rollback` is required; if not called, a reboot occurs after panic. On next boot, bootloader sees the pending verify state and rolls back? Let's check: There is "ota_state" might be set to PENDING_VERIFY by bootloader at boot time. If app previously was PENDING_VERIFY and rebooted without marking valid, bootloader can infer it failed and marks invalid / rollback. Let's search mental.

From ESP-IDF OTA docs:
```
esp_ota_mark_app_valid_cancel_rollback() - Marks the running app as valid.
esp_ota_mark_app_invalid_rollback_and_reboot() - Marks the running app as invalid, rollback to previous app and reboot.
```
Typical use:
```
const esp_partition_t *running = esp_ota_get_running_partition();
esp_ota_img_states_t ota_state;
if (esp_ota_get_state_partition(running, &ota_state) == ESP_OK) {
    if (ota_state == ESP_OTA_IMG_PENDING_VERIFY) {
        // run diagnostic
        if (diagnostic ok) esp_ota_mark_app_valid_cancel_rollback();
        else esp_ota_mark_app_invalid_rollback_and_reboot();
    }
}
```
If app crashes before checking state, it reboots and again boots the same new app with state PENDING_VERIFY. It can still check again? Maybe there is a boot loop if crash during early init before marking invalid. So you need watchdog or bootloader rollback counter.

The doc: "If the application fails to call esp_ota_mark_app_valid_cancel_rollback() within a certain number of boot attempts, the bootloader will rollback to the previous application." There is "bootloader rollback counter" maybe in otadata? Let's recall: There is `CONFIG_BOOTLOADER_OTA_DATA_ERASE`? Hmm.

I know there is "rollback and anti-rollback" in Secure Boot V2. Anti-rollback uses `CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK` and uses security version. It does automatic rollback? Let's not risk too much. The described scheme says "自检失败/超时 → 硬件 watchdog 复位 → bootloader 自动回滚到上一槽." The hardware watchdog reset alone won't mark app invalid. If app is stuck, task watchdog reset -> reboot to same PENDING_VERIFY app -> maybe app stuck again -> boot loop. Unless bootloader has rollback on PENDING_VERIFY after timeout. Need mention this as risk: cannot rely solely on hardware WDT reset; must call `esp_ota_mark_app_invalid_rollback_and_reboot()` explicitly or implement a boot attempt counter in NVS to mark invalid and rollback.

Let's verify exact ESP-IDF behavior. In `esp_ota_ops.c`, bootloader's `ota_ops.cpp`? There is `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` in bootloader. If enabled, bootloader checks `ota_state` and a "rollback counter" in `otadata`: there is `esp_ota_get_app_elf_sha256`? Actually I recall bootloader has `bootloader_ota_get_rollback_counter` maybe. Hmm.

Let's search memory snippets: In ESP-IDF Kconfig.bootloader:
```
config BOOTLOADER_APP_ROLLBACK_ENABLE
    bool "Enable app rollback support"
    default n
    help
        After updating the app, the bootloader can be configured to roll back to the previous app if the new app fails.
config BOOTLOADER_APP_ROLLBACK_TIMEOUT
    int "App rollback timeout (seconds)"
    default 5
    depends on BOOTLOADER_APP_ROLLBACK_ENABLE
    help
        The timeout in seconds for app rollback. If the app does not call esp_ota_mark_app_valid_cancel_rollback() within this time, the bootloader will roll back to the previous app.
```
Wait, how bootloader enforces timeout? Maybe it doesn't, maybe app has to call API; bootloader uses RTC timer? There is `esp_ota_mark_app_valid_cancel_rollback` that writes to otadata. If not called within timeout, bootloader won't know until reboot? But maybe bootloader can set a timer in RTC? Actually bootloader cannot run after boot. Maybe "timeout" is not real-time but bootloader records time at boot in RTC memory and app's `esp_ota_mark_app_valid`? Hmm.

Let's locate actual ESP-IDF doc from memory: The rollback process:
- The OTA update mechanism sets the OTA data to point to new app with state "New"?
- At boot, bootloader if state "New" sets it to "Pending Verify" before loading app.
- If app calls `esp_ota_mark_app_valid_cancel_rollback`, state becomes "Valid".
- If app calls `esp_ota_mark_app_invalid_rollback_and_reboot`, state becomes "Invalid", bootloader chooses previous app on next boot.
- If state remains "Pending Verify" and the device reboots (e.g. due to panic), the bootloader sees "Pending Verify" and will choose the previous app (rollback). That doesn't require app mark invalid. Actually yes, that's likely: if bootloader sees state PENDING_VERIFY, it rolls back. But if the app is stuck (not rebooting), it won't rollback until watchdog reset. Then on reboot, bootloader sees PENDING_VERIFY and rolls back. So hardware watchdog reset can lead to rollback if rollback enabled and state still pending. But if the app calls `esp_ota_mark_app_valid_cancel_rollback()` then later crashes, no rollback because marked valid. So self-check must not mark valid until fully stable. That seems plausible. But what about the "30 秒内未崩溃" self-check; if watchdog resets at 30s, bootloader sees pending and rolls back. Fine. But if app hangs without WDT? Need task WDT. If app gets into loop before starting WDT? Early init: if bootloader boots app but app crashes very early before enabling task WDT, maybe no timeout; could hang? The bootloader cannot know. But there is hardware RTC WDT enabled? IDF default has task WDT; maybe early boot has panic. But if app hangs in init before task WDT? The RTOS scheduler starts and idle task can watchdog? Usually interrupt watchdog maybe enabled. But mention.

Still issue: They say "自检失败/超时 → 硬件 watchdog 复位 → bootloader 自动回滚" but need ensure bootloader rollback enabled, and state remains PENDING_VERIFY; also the app must not call mark valid too early. Need mention.

2. Flash size/partition offset issues maybe: ESP32-S3 16MB flash. Partition offsets 0xc20000 + 0x3E0000 = 0x1000000. Fine. But partition table itself offset default 0x8000? They start nvs at 0x9000. That leaves 0x1000 for partition table? Could be okay (partition table offset 0x8000 size 0x1000? Actually default partition table offset 0x8000, max size 0xC00? The partition table usually starts at 0x8000, ends before 0x9000 if nvs at 0x9000. Fine. But there is no `otadata` initial? Fine.

Potential issue: `storage` SPIFFS at 0xc20000, size 0x3E0000. SPIFFS max size? SPIFFS on ESP-IDF is deprecated? It's okay up to 4MB. But they mention fonts/resources. But if OTA updates user app, does SPIFFS storage persist? Yes. But if factory reset / app partitions, not erased. Could need asset versioning. But not critical.

Critical: The partition table with factory + two OTA app slots consumes 12MB app slots + 4MB storage + NVS/otadata. But if they use Secure Boot v2 with signed app, the app image size may increase due signature block? max size? 4MB slot enough if app under 4MB. But with LVGL + fonts maybe could grow. They put fonts in SPIFFS, okay. Need mention reserve space for app due to OTA scratch? esp_https_ota writes directly to ota partition so no scratch needed. Fine.

3. Secure Boot v2 + OTA: They say "开发期可先用软校验（应用层验证 manifest 签名），生产发布前再硬件启用". But if using `esp_https_ota` with signed app images in Secure Boot v2, the OTA firmware must be pre-signed and maybe pre-encrypted? Secure Boot v2 requires image signed with private key, public key digest in eFuse. But if app is signed, the OTA binary must be the signed image (`.signed.bin`). The build script uses `esptool.py sign_data --keyfile signing.key build/app.bin` then copies app.bin to server. But `sign_data` command signs data? Need check. Secure Boot v2 uses RSA-PSS signature block appended. The command should be `idf.py secure-build`? Actually standard: `esptool.py --chip esp32s3 secure_verify_key digest.bin`? Hmm. Maybe not major.

Potential issue: Secure Boot v2 and `esp_https_ota` does not verify signature itself if secure boot enabled? The bootloader verifies at boot. The OTA code uses `esp_ota_ops` to write image. It must ensure image type and signature. `esp_https_ota` can handle signed app? It writes the entire binary. The bootloader verifies. okay.

But eFuse irreversible: if they burn Secure Boot key without ability to boot unsigned factory, and they have factory partition with maybe unsigned? Need ensure all images in all slots signed. Also "min_version anti-rollback" maybe issues. Need mention.

4. Missing server-side manifest tampering: They ask question 5. We can discuss.

5. OTA server SSL certificate: They embed server root certificate. But if using self-signed root, okay. Need include full chain and ensure cert PEM is correct. But not severe.

6. OTA resumption and NVS usage: `ota_resumption` uses NVS to store offset. With NVS size 0x6000 (24KB), if device also stores WiFi + OTA states, may be tight? Maybe okay but could use more. If using resumption, frequently writes to NVS during download, causing flash wear. Need mention wear leveling and flash endurance. But maybe not severe.

7. Partial HTTP download and PSRAM: They ask. We can answer.

8. Development ArduinoOTA in Phase 1: They need switch partition table. ArduinoOTA uses Arduino framework maybe not ESP-IDF? The hardware is ESP32-S3 with Touch LCD. They might use PlatformIO/Arduino. ArduinoOTA uses `Update` class which can write to flash. Default Arduino partition scheme for ESP32-S3 may be "Default 4MB with spiffs" etc. If they use custom partition table, they can configure in PlatformIO board_build.partitions. But if Phase 1 uses ArduinoOTA to flash new sketch to current app partition, it assumes partition table maybe app0/app1 but no factory? Arduino OTA can write to ota partition. Need detail. The boundary is at Board Support / partition table configuration. We can answer.

9. The self-check items for display terminal: Need define what "pass" means. We'll answer.

10. Missing "factory reset" path: If both OTA slots bad and factory exists, how to boot factory? Need a mechanism. The partition table includes factory but app flow doesn't describe when to set factory. The bootloader will not boot factory automatically if OTA data points to valid/invalid? Actually if ota_data invalid, bootloader boots factory. To recover from bad OTA, user can use GPIO forced factory reset or NVS flag. Missing. Also if both ota slots bad, factory is vital. Need provide a button/GPIO test to set factory and reboot; or app can call `esp_ota_set_boot_partition(factory)` and reboot after multiple failures. Need mention.

11. "Storage" SPIFFS and OTA rollback: If new firmware expects new assets in storage but rollback to old firmware, assets could be incompatible. Need include asset versioning and migration; don't wipe storage on OTA unless necessary. Maybe mention.

12. Power: OTA download is power-intensive (WiFi + flash write). Need ensure sufficient supply, no low-voltage during flash write causing corruption. Use brownout detector. They mention power? We need supplement.

13. Watchdog/rollback timeout config: They say `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` default 5s可调大. Need confirm: It may not work as they think. Let's be careful. We can state: This Kconfig option is not a runtime app timeout; it is used by bootloader? Actually if it doesn't exist maybe. But they mention it. We'll advise clarify.

Let's search mental exact Kconfig. In ESP-IDF, there is `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`; and maybe no separate timeout? I think there is `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? Hmm. The docs for "ESP-IDF OTA" say "The rollback process is triggered automatically if the application does not mark itself valid within a set time period. The set time period is configured using CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT." This indeed. But how bootloader enforces? It may use the RTC timer and on next boot? Wait app could mark valid after timeout. If it doesn't, next reboot rollback. The timeout is measured by bootloader? Actually bootloader runs before app; no time. Hmm maybe the app has an API that checks if timeout elapsed? The bootloader stores a timestamp in RTC slow memory? On boot, if state pending, bootloader can check the RTC time since last boot? No clock may not persist. It could use RTC timer running during app. If app doesn't mark valid and then WDT resets at timeout, bootloader sees pending and rolls back. But the "timeout" itself isn't a bootloader timer; it may be app's responsibility to reset itself after timeout via a timer. The Kconfig maybe sets the timeout for `esp_ota_mark_app_valid_cancel_rollback`? Hmm.

Let's not overcommit. We can phrase: "需要注意 IDF 的自动回滚仅在新固件因崩溃/WDT 复位后，bootloader 检测到仍为 PENDING_VERIFY 时才触发；若代码在自检前误调用 mark_valid，或卡死不产生复位，就不会回滚。必须显式设置一个自检超时定时器，失败路径调用 `esp_ota_mark_app_invalid_rollback_and_reboot()`。"

Also need mention boot attempts counter: If new app crashes very early before app code, bootloader might enter boot loop across ota_0/ota_1? Need maybe "bootloader rollback" has a rollback counter? We can mention implement additional NVS boot counter if not present.

Let's think of more severe flaws.

- "开发期免烧录: ArduinoOTA" but later "Secure Boot v2" production. Once Secure Boot v2 is enabled, you cannot use unsigned sketches or ArduinoOTA? ArduinoOTA can flash signed? Actually Secure Boot verifies app at boot; can still OTA flash if image signed? ArduinoOTA uses Update class which writes to flash, but bootloader will reject unsigned if secure boot enabled. Development before enabling okay.

- "传输层: HTTPS + 服务器证书校验" with `cert_pem` root certificate. But if using `esp_https_ota` API and only setting `cert_pem` to root CA, it verifies server certificate chain. For self-signed root, server cert must be issued by that root. If using server cert directly in `cert_pem` (leaf) may work if server cert is self-signed. Need ensure CN/SAN match URL. Fine.

- "完整性: esp_ota 内置镜像校验" — The `esp_https_ota` does not verify SHA256 manifest; it relies on image header checksum and signature. The manifest `sha256` is not checked by provided code. Need check. If they intend to verify manifest signature, okay. But the code example downloads latest.bin directly; manifest just checks version. The `sha256` field is not used. Need mention: manifest sha256 not checked, so an attacker who can alter manifest without changing firmware could cause downgrade? Actually HTTPS protects transport, server compromise? But application should verify manifest signature and SHA256. The flow says "拉取 manifest.json → 版本号 > 当前 → esp_https_ota 下载到空闲分区", no signature verification. If they defer Secure Boot, any server compromise or DNS hijack with valid cert? cert pinned. But they should still verify manifest signature and firmware SHA256 before writing to flash. That's important. They mention "开发期先软校验（应用层验证 manifest 签名）" but not in flow. So a critical gap: manifest/firmware application-level verification missing in design; relying solely on transport and optional secure boot. If using HTTPS only, server cert protects in transit but not from server compromise, malicious CI build, or misconfigured server. We can highlight.

- "esp_https_ota" writes to the *next update partition* directly. If `spiffs` storage is on same flash, power loss during OTA write may corrupt flash? But dual partition protects current app; only target partition corrupt. But flash erase/write may affect power. Need mention brownout.

- "factory 兜底" — But if both OTA partitions become invalid? Bootloader selects factory if otadata invalid. But `esp_ota_mark_app_invalid_rollback_and_reboot` sets selected OTA invalid and chooses previous. If previous also invalid, maybe fallback to factory. But not explicit.

- "anti-rollback via security version" — If they use Secure Boot v2 anti-rollback, could brick device if security version set incorrectly and manifest min_version not aligned. Need mention.

Need sort severity. Which are most severe?

Let's list possible defects:
A. 回滚自检状态机有致命误解/未实现显式失败标记，硬件看门狗复位不保证回滚，可能 boot loop. (Severe)
B. 缺少 manifest 签名校验和固件 SHA256 校验的应用层闭环；`sha256` 只是摆设；开发期无 Secure Boot 时只能靠 HTTPS 传输，无法防篡改/服务器侧错误. (Severe)
C. factory 兜底没有落地：无 GPIO/命令触发回出厂、无 OTA 失败次数限制、无法切换 boot 分区；分区表虽有 factory 但流程没用. (Severe/High)
D. Secure Boot v2 启用后开发/生产切换与 eFuse 不可逆风险：开发期不启用，但生产前需完整测试签名、多个 app 槽签名、 factory 签名，否则启用即砖；且 eFuse 烧录不可逆，没有明确密钥管理/备份/设备批次. (High)
E. 分区表/NVS 尺寸与 OTA resumption 磨损：NVS 24KB 可能紧张，OTA resumption 频繁写 NVS 引起 flash 磨损；SPIFFS 4MB 不足以存完整 LVGL 字体/图片？ Maybe not most severe. Could be lower.
F. OTA URL/服务器证书管理缺少可更新机制：内置根证书固化，若证书到期/换服务器，无法远程更新? They could update via OTA. But once cert pinning baked in, can't update root cert without OTA signed by old. Need include. Could be medium.

But asked 3-5 most severe. We'll choose 5.

Let's think more deeply about ESP-IDF rollback: The described self-test items "启动 30 秒内未崩溃（task watchdog 兜底）" but they also include "显示初始化" etc. If the app's task watchdog is not properly initialized/feeding before LVGL init completes, false rollback. Need design.

Another critical issue: The OTA flow says "下载完成 → 校验（签名/哈希）→ esp_restart()". But `esp_https_ota` internally already verifies image header and signature? If using Secure Boot, bootloader verifies at next boot. The app-level "校验" before restart is ambiguous. For Secure Boot v2 no app-level signature verification needed; for soft verification, need use `esp_ota_verify`? There is no public API to verify signature in app? They could use `esp_ota_ops` to compare digest. Need not dwell.

Another issue: "ota_resumption = true" and "断点续传存 NVS": Does `esp_https_ota` with `ota_resumption` actually support resuming across reboots? It stores the pause offset in NVS? Actually `ota_resumption` config in `esp_https_ota_config_t` maybe supported since IDF V5? The API has `ota_resumption` bool. It may use NVS. Need ensure custom NVS partition is accessible and enough. It's a high-level feature. Could be okay.

Another issue: Using SPIFFS for fonts/resources and OTA. SPIFFS is deprecated in favor of LittleFS/FatFS. But not severe.

Potential issue with `phy_init` data at 0x11000. On ESP32-S3, `phy_init` may need to be at 0x11000? yes. Size 0x1000 okay.

Potential issue: secure boot v2 with 16MB flash and DIO/DOUT? Not relevant.

Potential issue: OTA trigger from background task. If device is a status display, OTA download could degrade WebSocket/LVGL performance. Need schedule: check updates only when idle, cap download rate? Not severe.

Potential issue: "免烧录快速迭代" via ArduinoOTA in Phase 1 makes sense, but if using LVGL + PSRAM and custom partition maybe ArduinoOTA may not handle 16MB? It does. The transition to IDF custom partition table could require full serial flash once. We'll answer.

Need answer 5 questions:

1. ArduinoOTA vs esp_https_ota切换分区表是否需切换？边界？
- ArduinoOTA (Arduino-ESP32) uses the same ESP-IDF OTA mechanism? ArduinoOTA library uses `Update` class writing to `U_SPIFFS`? Actually ArduinoOTA uses `Update.begin` writing to flash. It can use the current active OTA partition? Let’s recall: ArduinoOTA on ESP32 can update sketch and filesystem depending on command. It uses `esp_ota_get_next_update_partition` and writes to it. The partition table can be custom; if custom has ota_0/ota_1, ArduinoOTA will work. It doesn't know about factory perhaps. The main boundary is not the OTA mechanism but the partition table and bootloader config. If Phase 1 Arduino uses default Arduino partition (maybe `default.csv` with ota_0/ota_1, maybe no factory), switching to custom IDF partition table with factory+ota+spiffs requires reflashing partition table and likely full firmware because partition layout changes. They can use the same custom partition table from the start in Phase 1. In Arduino/PlatformIO, set `board_build.partitions = custom.csv` and ensure "Flash Size 16MB" and "Partition Scheme Custom". Then ArduinoOTA will write to ota_0/ota_1. When moving to esp_https_ota, you can reuse same partition table and bootloader rollback config. But if ArduinoOTA lib does not understand rollback marking, it may not call `esp_ota_mark_app_valid_cancel_rollback`, leaving app PENDING_VERIFY forever. Thus if Phase 1 uses bootloader rollback enabled, every ArduinoOTA update may roll back after reboot. That's important: ArduinoOTA may not mark app valid. Need check: Arduino's `Update.end` may not call `esp_ota_mark_app_valid_cancel_rollback`. The default Arduino bootloader doesn't use rollback? If CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not enabled in Arduino SDK, then not issue. But if using custom IDF bootloader with rollback, ArduinoOTA may need modification. So the boundary includes the bootloader rollback configuration. If using Arduino's precompiled bootloader with rollback disabled, fine. For Phase 2, you need rollback enabled bootloader and self-check. So transition: keep same custom partition table; but bootloader may need to be flashed from IDF build, and application must call mark valid. Also Phase 1 ArduinoOTA uses unsigned OTA over bidirectional TCP (not HTTPS); not suitable beyond LAN. Need not require server.

2. Secure Boot v2 对调试（JTAG、串口日志）影响，如何最小化？
- Secure Boot v2 doesn't encrypt flash; it only verifies app. It doesn't block UART logging by itself. JTAG debugging may be restricted if `CONFIG_SECURE_BOOT_ALLOW_JTAG`? Actually Secure Boot may disable JTAG if eFuse `JTAG_DISABLE` set separately. By default enabling Secure Boot doesn't necessarily disable JTAG? Need verify. In ESP32-S3, eFuse `JTAG_DISABLE` can be burned. Secure Boot V2 may not require disabling JTAG. But for production may choose to disable. To minimize: Do not burn `JTAG_DISABLE`; do not enable Flash Encryption; keep UART ROM messages? Secure Boot may block boot if unsigned but after boot OS log still works. Use `CONFIG_SECURE_BOOT_ALLOW_ROM_BASIC`? There is `CONFIG_SECURE_BOOT_ALLOW_JTAG`? I'd say:
  - Secure Boot v2 only checks image signature at boot. It does not need Flash Encryption, so UART logs remain available.
  - JTAG may remain available if eFuse `SECURE_BOOT_ENABLE` is set but `JTAG_DISABLE` not burned. However some security features like "Disable JTAG" can be independently burned. To optimize development, keep `CONFIG_SECURE_BOOT_ALLOW_JTAG` enabled and don't burn `JTAG_DISABLE` eFuse until final production.
  - But if enabling Secure Boot in development, you must sign every build. That complicates rapid iteration. Recommended development builds remain unsigned, Secure Boot enabled only on a dedicated "secure build" test device, not on all development boards. Separate eFuse lifecycle.
  - Also Secure Boot V2 may require `CONFIG_SECURE_BOOTLOADER_MODE` and public key. You can maintain a "dev key" and only burn on a few devices. The production key must be generated offline and stored in HSM.
  - Use `esp_secure_cert`? No.

3. 8MB PSRAM 下 partial_http_download 是否值得？缓冲区策略？
- The AI Agent display app likely firmware <4MB, maybe small. `esp_https_ota` default uses RAM buffer? The `esp_https_ota` downloads to flash directly via `esp_ota_write`, using a 4KB buffer in internal RAM. PSRAM is not required for OTA. Partial HTTP download is an optimization for huge images to avoid timeouts and reduce memory; with 8MB PSRAM, you could allocate a larger buffer (e.g., 16–32KB) in PSRAM, but PSRAM slower and cache considerations. It's generally not needed for <4MB. The OTA write speed is usually limited by flash erase/write and network, not buffer size. Use `partial_http_download` if you need to download over unstable connections or to show progress with range requests; but it adds complexity: server must support Range. For this device, not necessary. If used, buffer in internal RAM 4–8KB; avoid large PSRAM buffer because OTA write may call flash operations while PSRAM cache disabled? Actually flash writes require cache disabled; buffer in PSRAM may be inaccessible. So use internal RAM buffer. Recommendation: skip partial_http_download; keep `ota_resumption` for unstable network.

4. 回滚自检项对弱交互应用什么算通过？
- The app needs to prove it can perform its core function: boot, read config, connect to WiFi, establish WebSocket, receive/parse at least one status message, render it to LVGL successfully, and touch input responds. Since no sensor, self-check should include:
  a) System startup successful: `esp_ota_get_state_partition` returns `ESP_OTA_IMG_PENDING_VERIFY`.
  b) Peripherals: LVGL display init, backlight on, touch controller I2C ACK, read version/status.
  c) Network connectivity: WiFi connect to configured AP and IP acquired, DNS resolution for OTA server perhaps.
  d) Application service: WebSocket client connects to broker/server; receives a valid status message within timeout (or at least subscribes). Maybe if server not available, do not fail rollback? Need consider. For “AI Agent Status display”, if server temporarily unavailable, marking invalid would cause unnecessary rollback. So self-test should distinguish device-local failures (display/touch/WiFi hardware) from remote/service failures. WiFi can connect but WebSocket server may be down; maybe that's not firmware invalid. So required self-check: display + touch + WiFi station connection + OTA task alive. WebSocket connection/render test should be soft: if no remote message, render a local test screen and still pass; log warning. Do not rollback due to temporary cloud/agent outage. But design should have a "minimum viable local UI" always available.
  d) Version self-report: app_desc version matches manifest.
- Pass criteria: all critical hardware/peripheral init pass; network stack up; a local test pattern rendered; timer feeds WDT. Mark valid only after N seconds of stable operation (e.g., 30–60s) without reboot. If any critical item fails, explicitly mark invalid and reboot.
- Need mention "watchdog feed must be active during LVGL/test; avoid false rollback".

5. manifest.json 的签名作为 Secure Boot 之前过渡方案？
- Yes, but only if done correctly. It provides application-layer authentication/version policy; it does not protect against a local malicious firmware that bypasses OTA app. If attacker can flash via UART/JTAG or replace firmware, manifest signature doesn't help. It protects the OTA channel against server compromise/active network attacks if you verify:
  - manifest has a `sha256` of firmware.
  - manifest itself signed (RSA/ECDSA) with a public key embedded in app.
  - Check timestamp/nonce/anti-rollback? To prevent replay/downgrade, include `version`, `min_version`, `issued_at`, and possibly `nonce` from device? But device clock may not be reliable. At minimum verify signature and version monotonicity using app's stored last accepted version. Manifest signature is a good transition if firmware image is not Secure Boot-signed; you can compute SHA256 of downloaded image before flashing and compare. But if using `esp_https_ota` directly downloading to flash, it writes as it downloads; so to verify SHA256 first, you need either download to a temp buffer/PSRAM or file, not directly write to OTA partition, or use an API that verifies after write but before reboot and can mark invalid. For 4MB firmware, you cannot hold in RAM? 8MB PSRAM maybe can hold 4MB, but memory fragmentation/PSRAM may be okay? Better download to an unused area? Could use `esp_https_ota` to write to OTA partition; then after download, read back and calculate SHA256? This is time-consuming and still if bad you need mark invalid and revert? But if invalid image is in ota partition and you don't reboot, current app still running. You could verify hash after download, but the image has been written; if bad, you can call `esp_ota_set_boot_partition`? Actually you can mark that OTA partition invalid? There is `esp_ota_mark_app_invalid_rollback_and_reboot` only for running app. Better to use `esp_https_ota` with `bulk_flash_erase` and then verify? Not necessary. Alternative: download firmware to SPIFFS storage first (if space) then verify SHA256 and use `esp_ota_ops` to write to ota partition. But dual copy flash wear. With PSRAM 8MB, you could allocate 4MB PSRAM buffer to store image, compute hash, then write to OTA via `esp_ota_write`. But due to cache constraints maybe internal RAM? Write from PSRAM to flash? `esp_ota_write` can copy from PSRAM. Might be okay but memory large. Simpler: Use `manifest.json` signature and rely on HTTPS for transport; just check version and size. Hash verification can be implemented by `esp_https_ota` with `http_config.buffer_size`? Not.

Maybe answer: Yes, as transition but not sufficient; require firmware SHA256 verification and manifest signature; can use `mbedTLS` to verify signature. If using `esp_https_ota`, you can set `http_config` to download into buffer? Hmm. The better approach: Build the OTA image with a custom `.bin` containing an embedded manifest? Or use `advanced_https_ota` example with `esp_https_ota_begin` / `esp_https_ota_perform`? It still writes on fly. To check SHA256 before writing to OTA, you may need custom download and write.

Maybe mention "为了在无 Secure Boot 阶段真正防篡改，不能只依赖 HTTPS；manifest 签名 + firmware sha256 是必要但不充分。最好实现为：HTTPS 下载到临时存储（PSRAM 或 SPIFFS）→ 验签 → 校验哈希 → 再 `esp_ota_write` 到目标分区。"

Now final conclusion. Need decide if scheme feasible. It is overall feasible with modifications. Need say "方案总体方向可行，但当前设计 v0.1 不能直接用于生产"。 Need list modifications: fix rollback state machine; add app-level verifier; implement factory fallback; clarify Secure Boot enable/lifecycle and key management; adjust partition/NVS; perhaps include encrypted flash? Not needed but maybe optional. Need mention if device displays status via WiFi + WebSocket, flash encryption maybe not necessary unless data sensitive. But Secure Boot only is not enough for confidentiality; but purpose not critical.

Need provide additional omitted key points:
- Partition table: include `erase_size`, alignment? They are mostly aligned. Need include `ota_data_initial`? Not needed.
- Rollback timing sequence: Need understand exact bootloader sequence: After reboot, bootloader sees PENDING_VERIFY and chooses previous app; the app must not mark valid too early. Self-test must start after critical init. Include `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? Need mention if using "rollback timeout" config, but the app still must explicitly mark invalid or reboot. Also need test rollback before production.
- Security: Secure Boot V2 alone verifies source but doesn't encrypt. Consider Flash Encryption for protecting Wi-Fi credentials and assets. But Flash Encryption + OTA requires pre-encrypted images or NVS encryption. Could complicate. If device stores credentials in plaintext, local attacker can read via UART flash dump? Actually flash encryption prevents. But maybe not necessary for this use. Mention optional.
- OTA server certificate renewal: implement certificate rotation or dual root? Because `cert_pem` hard-coded. Need OTA app update path for new cert. Could include future root cert in manifest? Not critical.
- Power: Brownout detector and stable 3.3V. During OTA flash writes, supply current spikes; use sufficient capacitor. Avoid OTA while battery low; check voltage before OTA.
- Flash wear: OTA resumption in NVS may cause wear; use LittleFS instead of SPIFFS? NVS wear leveling yes. OTA update frequency likely low. Need write only when necessary.
- Logging: Preserve logs during rollback; write crash reason to NVS to diagnose.
- Testing: Need test power loss at every step of OTA (erase, write, post-signature), test rollback with both good and bad images, test factory fallback, test server down/Throttle.

Need maybe mention "esp_https_ota with `cert_pem` root CA and `ota_resumption` is okay, but manifest URL should be versioned and not latest.bin? latest.bin with manifest is fine."

Now write report in Chinese.

Need structure:
- 评估摘要
- 一、严重缺陷/风险（按严重度排序）
  1. 回滚自检/看门狗回滚时序存在致命漏洞
  2. OTA 应用层验证缺失，manifest sha256 是摆设，开发期无 Secure Boot 时不可信
  3. factory 兜底没有执行路径，无法实际回退出厂
  4. Secure Boot V2 / eFuse 生命周期管理不足，生产启用可能变砖
  5. 分区/NVS/OTA resumption 设计存在资源与磨损风险（或服务器证书固化缺少轮换）
- 二、五个待评估问题回答
- 三、总体结论与必须修改项
- 四、补充遗漏关键点

Need ensure not too long? Desired oververbosity 5 but user requested complete report. We can be thorough.

Let's craft details.

Detailed point 1:
"方案将自检失败/超时归因于硬件 watchdog 复位后 bootloader 自动回滚。这个理解不完全。IDF 回滚依赖 otadata 状态。如果你在自检期间已调用 mark_valid，失败就取消了回滚。若卡死且看门狗未复位，系统不会回滚。若崩溃反复发生在 app 早期且 bootloader 未启用 rollback / otadata 被处理？" Need precise.

Let's phrase:
- ESP-IDF 的 `esp_ota_mark_app_valid_cancel_rollback()` 是应用主动标记。硬件 WDT 复位若发生在用户代码已经调用 `mark_valid` 之后，即使自检后续失败也不会回滚。
- 若自检超时只是“等 30 秒”而没有显式调用 `esp_ota_mark_app_invalid_rollback_and_reboot()`，则只会停留在 PENDING_VERIFY，下一次复位仍可能启动同一新固件，形成 boot loop。
- 若 app 在早期崩溃而没有触发 WDT（比如中断关闭、OS 启动前卡死），可能不会产生复位，设备停住，也不会回滚。
- 因此风险是：设计把“看门狗复位”当作回滚触发条件，但实际必须通过软件状态机显式标记 invalid 或确保 bootloader rollback 选项正确处理 PENDING_VERIFY。需要在自检超时器中调用 `esp_ota_mark_app_invalid_rollback_and_reboot()`，并配合 `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` 和"启动失败计数"。还要注意不要过早 mark_valid.

Let's ensure exact: "bootloader 自动回滚" actually might happen if state PENDING_VERIFY on reboot. But the user code may need hardware WDT to cause reboot. We can state "硬件 WDT 复位只是产生一次重启，真正回滚取决于 bootloader 看到 otadata= PENDING_VERIFY；这需要 bootloader 开启了 rollback。若应用在自检失败后又调用 mark_valid 或者长时间不重置，则无法保证回滚。" That's safe.

Point 2:
- The manifest flow doesn't validate manifest signature or firmware SHA256. The code shown uses `esp_https_ota` directly to latest.bin. If Secure Boot not enabled in dev, attack scenario: a malicious/compromised server or a MITM with fake cert? HTTPS root pinned prevents MITM, but if server compromised or insider threat, could push firmware that passes transport and image checksum but not authorized. Manifest sha256 not checked, so corrupted file could be flashed? Actually image header checksum catches corruption; but malicious content could be flashed.
- Need application-level public key signature verification for manifest and firmware hash. This is essential until Secure Boot v2 enabled. In production with Secure Boot v2, bootloader will verify signature, but still manifest signature helps version policy and avoids downloading malicious files? Actually secure boot only at boot; malicious image written then reboot -> bootloader rejects, but now device boots old app? Could be possible to rollback. Good.
- Severity: high.

Point 3:
- factory partition exists but no description how to boot it. Need add:
  - A factory reset service: hold touch button during boot, or call `esp_ota_set_boot_partition(esp_ota_get_factory_partition())` then reboot.
  - After N failed OTA attempts / rollback loops, automatically fallback to factory.
  - Ensure factory app is also signed if Secure Boot enabled and can operate.
- Otherwise factory is dead weight.

Point 4:
- Secure Boot v2 life cycle:
  - eFuse one-time, cannot revert. Enabling on production hardware without staged validation can brick.
  - Need generate and store signing keys securely; if key lost no future OTA.
  - Must sign factory, ota_0, ota_1 all images; if factory unsigned, fallback impossible.
  - Need define how debug devices with Secure Boot disabled can be updated to Secure Boot enabled? Cannot enable via OTA; require physical access to burn eFuse and flash signed bootloader.
  - Need separate development key and production key; test on sacrificial units; have a "pre-production" phase with production key but no anti-rollback until sure.
  - Need consider anti-rollback security version and manifest min_version can itself cause brick if set too high.

Point 5:
- Resource/wear:
  - NVS 24KB maybe too small for WiFi + OTA resumption + rollback counters. If using ArduinoOTA, NVS maybe also used. Need calculate. Increase to 0x8000 or 0x10000 if offset allows? Could adjust. But currently nvs ends at 0xf000; otadata at 0xf000. Need if increase NVS to 0x8000 (32KB), then otadata at 0x11000? But phy_init at 0x11000. That would conflict. We can revise partition table:
    ```
    nvs 0x9000 0x8000 (32KB)
    otadata 0x11000 0x2000
    phy_init 0x13000 0x1000
    ...
    ```
    But partition offsets usually not need contiguous? They can be. Could increase NVS to 0x8000 ending at 0x11000. otadata 0x11000, phy_init 0x13000. Then app offset maybe still 0x20000. That works. Or use separate `nvs_ota` partition for OTA resumption. Simpler.
  - `ota_resumption` uses NVS to store resume state; each flash write is wear. If OTA frequently interrupted, repeated writes. NVS wear leveling but still finite. 24KB small. Could store offset only on pause, not every chunk.
  - SPIFFS deprecated; 4MB okay but consider LittleFS. Also storing assets in SPIFFS, if app version changes & assets changed, need asset version manifest and maybe download assets separately? Not in scope.

Alternative severe risk: server root cert pinning. We can mention as "其他重要风险" rather than top 5.

Need maybe include "分区表 factory slot 4MB plus two OTA 4MB plus storage 4MB works; but OTA apps max size 4MB minus signature block. Ensure app with LVGL fits; if not, need adjust. With 8MB PSRAM you might embed fonts in flash; but 4MB slot limit okay."

Now answer questions thoroughly.

Question 1:
- It's the partition table and bootloader config that are the boundary.
- ArduinoOTA with ESP32 Arduino core uses the same OTA partition mechanism. If you build Phase 1 with Arduino core and a custom partition CSV with factory/ota_0/ota_1/spiffs, ArduinoOTA can OTA to ota_0/ota_1 without a partition change. Need ensure Arduino core's board options: Flash Size 16MB, Partition Scheme "Custom" pointing to same CSV. Set bootloader to one from Arduino? If you need rollback enabled, Arduino's precompiled bootloader might not have `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`. In that case you must build bootloader from ESP-IDF with same partition table and rollback enabled, then flash it once. Phase 1 may not need rollback? But to keep consistent, use same custom partition table from day 1. If not, when switching from Arduino default to IDF custom, you need one-time full serial flash (bootloader + partition table + app + filesystem) because offsets change.
- The OTA protocol difference: ArduinoOTA is not HTTPS; it's a proprietary TCP OTA and not secure. It's fine on isolated dev network only. It may not call `esp_ota_mark_app_valid_cancel_rollback` if rollback enabled. Either disable rollback in Phase 1 or patch ArduinoOTA/`Update.end` to mark valid. So boundary: security, rollback semantics, bootloader, partition table.
- Recommendation: Use the same custom partition table from start; use ArduinoOTA only for rapid iteration in Phase 1 with rollback disabled, but flash IDF bootloader and set partition table once at beginning. Phase 2 switch to esp_https_ota without partition table changes.

Question 2:
- Secure Boot V2 does not by default disable JTAG/serial logging; but it may restrict boot for unsigned code. It's possible to keep JTAG if you don't burn `JTAG_DISABLE` eFuse and keep `CONFIG_SECURE_BOOT_ALLOW_JTAG`? Need be careful: There is `CONFIG_SECURE_BOOT_ALLOW_JTAG`? Actually there is `CONFIG_SECURE_BOOT_ALLOW_ROM_BASIC` maybe irrelevant. I'll phrase:
  - Do not burn `JTAG_DISABLE` and `DISABLE_DL_DECRYPT`/`DISABLE_DL_CACHE` eFuses while in development.
  - Use a dedicated "secure boot enabled but debug-friendly" test board; do not enable Secure Boot on all development boards. You can't disable it once eFuse burned, but you can choose not to burn it on dev units.
  - Keep serial logging enabled; Secure Boot V2 does not require disabling UART. But if Flash Encryption is enabled, it also doesn't block logs. However Secure Boot v2 often combined with flash encryption; that can complicate JTAG and core dumps. For debugging firmware logic, do it before burning the production Secure Boot key. For secure boot testing, use a separate device.
  - To minimize build pain: use a "dev key" generated locally for secure boot, sign automatically in CI, and flash via UART. Keep the production key in HSM/offline.
  - Also ensure `idf.py openocd`/JTAG works with secure boot enabled if eFuse not disallow JTAG.
Question 3:
- `partial_http_download` not necessary. The firmware image probably <2–3MB, 8MB PSRAM doesn't automatically make it beneficial. `esp_https_ota` writes to flash through internal buffers; partial download is for very large images >4MB or unreliable links requiring Range.
- If used, use internal RAM 4–8KB buffer; avoid placing OTA write buffer in PSRAM because flash cache disabled during writes may make PSRAM inaccessible. But maybe ESP32-S3 has cache coherency? Still internal RAM safer.
- Better strategy: enable `ota_resumption` only; use event callbacks to throttle/UI progress. Do not enable partial_http_download unless tests show HTTP timeouts or memory issue.

Question 4:
- Define "local critical pass" vs "remote service pass":
  - Must pass: boot crash-free, LVGL display init and renders local test screen, touch controller responds to I2C read, WiFi STA connects and obtains IP, OTA task created.
  - Should not cause rollback: WebSocket server unavailable, no agent message, timeout to remote service. Reason: firmware update may be fine but server down; rolling back doesn't fix.
  - Could mark valid after local critical passes + a stable run timer (e.g., 60s) and optionally one successful remote update/status message if available within window; if remote not available but local pass, log warning and still mark valid.
  - Version self-report should be checked from `esp_app_get_description()` at boot.
  - The app should have a "safe mode" local status page to verify display/touch when network/server absent.

Question 5:
- Yes, as transitional but requires:
  - Sign manifest with RSA/ECDSA using embedded public key.
  - Include firmware SHA256 in manifest, and verify downloaded image hash before committing to OTA partition. That may require downloading to temp/PSRAM/storage first.
  - Include anti-rollback: version > current, monotonic stored in NVS, min_version, timestamp/nonce to prevent replay (though timestamp needs secure clock; NTP may not be secure; at least server-signed timestamp).
  - Use HTTPS with pinned cert plus manifest signature. Without Secure Boot, a local attacker with UART/JTAG can still flash arbitrary firmware. So it's not equivalent; it only protects OTA channel.
  - Once Secure Boot v2 is enabled, manifest signature remains useful for server-side release policy and version control, but not mandatory for integrity if all apps are signed. Still recommended to check sha256/version before downloading.
- Need mention "manifest JSON itself can be subject to rollback/replay; use `issued_at` and reject old manifests."

Now final conclusion:
- 方案方向正确，但 v0.1 存在关键缺陷，不能直接生产/Phase 2。
- Must fix before design freeze:
  1. Rewrite rollback state machine (explicit invalid mark, boot attempt limit, test).
  2. Implement application-layer manifest+firmware verification if Secure Boot deferred.
  3. Add factory fallback execution path and test.
  4. Formalize Secure Boot key/eFuse lifecycle.
  5. Adjust partitions/NVS and evaluate wear.
- Then feasible.

Supplement omissions:
- Factory reset/recovery trigger.
- Asset/SPIFFS versioning and migration.
- Bootloader/log/crash diagnostics in NVS.
- Test plan: power-loss injection at each OTA phase; rollback test; downgrade/replay test; certificate expiry/rotation.
- Power/brownout: check VBAT/5V stability; brownout detector; do not start OTA on low battery or high temperature.
- Flash wear: OTA frequency; NVS writes; SPIFFS wear.
- Server: use versioned immutable artifacts, not mutable latest.bin over time; use manifest as pointer; backup previous releases.
- Network: OTA background task should not starve LVGL/WebSocket; set WiFi power save carefully during OTA download; keep connection stable, maybe disable sleep during OTA.
- Security: if device stores AI agent status with sensitive data, consider Flash Encryption. At minimum encrypt NVS keys.

Need maybe include "esp_https_ota server cert `cert_pem` root CA must be valid; if server cert rotates, need OTA update root. Could include two root CAs in certificate bundle? The `cert_pem` can be a bundle? `esp_http_client` supports a PEM with multiple certs? May be okay. Mention."

Let's write final in Chinese.

But before final, let's ensure there are no other hidden severe issues. The user requested specifically "3-5 个最严重的缺陷/风险（按严重程度排序）"—we'll list 5. Need make sure not too generic. We'll produce.

Let's maybe include a table at top summary.

Now format.

Potential phrases:
"1. 回滚时序/看门狗触发回滚设计不可靠（致命）"
Detailed:
```
当前设计将硬件 WDT 复位等同于触发回滚。实际上：
- IDF OTA 回滚的关键是 otadata 中的状态。自检通过后必须调用 esp_ota_mark_app_valid_cancel_rollback()；失败必须调用 esp_ota_mark_app_invalid_rollback_and_reboot()。
- 如果自检超时只是“等待 30 秒”而没有显式 mark invalid，则状态仍为 PENDING_VERIFY。看门狗复位发生后，bootloader 是否回滚取决于是否开启 rollback 支持；即使开启，也是因为状态未变 VALID，而非看门狗本身。
- 一旦自检期间误调 mark_valid，后续崩溃/WDT 不会回滚。
- 若应用在使能看门狗前卡死，设备不会复位，更不会回滚。
```
Need confirmation: If bootloader sees pending verify, it boots previous app after WDT reset. That's true I think. We'll phrase "通常情况下，在启用 rollback 支持且状态保持 PENDING_VERIFY 时，下一次复位后 bootloader 会选择上一槽；但仍需显式处理。" Good.

"建议：实现一个 `ota_self_test_task`，在超时前设置 `ota_self_test_result`；调用 mark_valid or mark_invalid; 开启 task WDT 和 RTC WDT; Never call mark_valid before self-test complete. 增加 NVS 启动失败计数器，若同一新固件连续 N 次进入 PENDING_VERIFY 仍未通过，强制 mark invalid or factory."

Let's include.

Second: "应用层校验缺失，manifest.sha256 是摆设"
```
开发期没有 Secure Boot 时，设计只依赖 HTTPS cert_pem。HTTPS 只保证传输通道，不能保证服务器内容本身可信。manifest.json 未签名，sha256 未校验。一旦服务器被攻陷、CI 产物被替换、DNS/SSL 证书配置错误（例如误信任公共 CA），设备可能写入恶意/错误固件。即使 bootloader 拒绝，也会导致回滚/服务降级。
```
Actually cert_pem rooted private CA prevents public CA. But server compromise remains.

Need mention "esp_https_ota 内部镜像校验是格式完整性，不验证作者身份；开发期不能替代签名。"

Third: factory fallback not implemented:
```
分区表中 factory 是最后兜底，但流程没有 `esp_ota_set_boot_partition(factory)` 或 factory reset 逻辑。bootloader 不会因为 ota_0/ota_1 都失败自动回 factory；需要在应用层检测连续回滚次数或按键中断，显式切换。
```
Need maybe "if otadata invalid, bootloader will boot factory, but you can't rely on corruption." Good.

Fourth: Secure Boot eFuse lifecycle:
```
eFuse 不可逆，启用前必须确认所有可启动槽签名。若 factory 未签名、bootloader 配置错误或密钥丢失，设备可能在 OTA 失败后永远无法恢复。生产启用后 JTAG 调试可能受 eFuse 限制。需要逐步启用：开发期不烧 eFuse；预生产烧 dev key；生产烧 prod key 并写保护；所有阶段保留离线密钥备份和签名构建脚本。
```

Fifth: "NVS 尺寸 + OTA resumption + SPIFFS":
```
nvs 0x6000 (24KB) 在同时保存 WiFi 凭证、OTA 重试状态、断点续传偏移、回滚计数器时可能不足。ota_resumption 可能频繁写 NVS，增加磨损。SPIFFS 已不推荐，建议 LittleFS。 8MB PSRAM 不解决 OTA 缓冲问题。
```
Maybe not "severe" but include.

Could instead include "证书固定/服务器证书轮换缺失" as fifth. Hmm. Which is more severe? NVS size is not severe; cert rotation is more likely. But user's top risks already mention eFuse etc. We'll maybe combine fifth as "分区/资源与证书轮换两个中等风险" or choose 5: "OTA URL/证书固定与服务器运维缺少轮换". Let's decide.

The request says "3-5 个最严重的缺陷/风险". We can include 5: rollback, app verification, factory fallback, secure boot lifecycle, resource/NVS. The certificate rotation can be in omitted points. That's fine.

Now answer question 1 with details.

Potential extra: "ArduinoOTA 与 esp_https_ota 切换" We need mention "ArduinoOTA does not support HTTPS/签名; if Phase 1 uses ArduinoOTA it may not use IDF's rollback API; need check Update.end."

Let's phrase:
```
边界不是 OTA 客户端本身，而是：
1) 分区表 CSV：二者都必须使用同一个自定义分区表。Arduino 默认分区通常没有 factory+双 OTA+SPIFFS，Layout 变化需一次串口全擦写。
2) Bootloader 配置：ESP-IDF 回滚/安全组件在 bootloader 中。Arduino 预编译 bootloader 可能未启用 rollback，Phase 2 需更换 bootloader。
3) 安全/签名：ArduinoOTA 是明文自签 OTA，仅限隔离内网；Phase 2 HTTPS+签名。
```
Need maybe "如果 Phase 1 用 PlatformIO+Arduino，配置 `board_build.partitions = custom_16MB.csv` 且 `board_upload.flash_size = 16MB`；如果使用 Arduino IDE 需要在 tools 菜单选择 custom partition scheme."

Question 2:
```
Secure Boot V2 本身不强制禁用 UART/JTAG，除非你额外烧断 JTAG_DISABLE 等 eFuse。因此最好的最小化策略是：不要在开发设备上烧 prod eFuse；开发期保持 Secure Boot 关闭或使用 dev key；串口日志照常。生产前期在专用“安全性测试机”上烧 dev key 验证 OTA/回滚，保留 JTAG；最终批量时再烧 prod key，并烧断 JTAG_DISABLE（按需）。注意 Secure Boot 开启后每一次 OTA 固件都必须签名，否则 bootloader 拒绝。Flash Encryption 是独立项，如果开启会进一步限制 JTAG/flash 读取，调试更复杂。
```

Question 3:
```
不值得。partial_http_download 是为了超大固件或极不稳定网络。该设备固件通常在 4MB 槽内，esp_https_ota 默认内部 RAM 缓冲已够。PSRAM 不适合作为 flash OTA 写缓冲（写 flash 时 cache 可能被禁用）。若启用，应使用 internal RAM 4~8KB，不要使用 PSRAM 大缓冲。优先使用 ota_resumption 即可。
```
Need maybe "如果你预计固件会接近 4MB，可开启 partial_http_download with 8KB internal buffer to improve reliability."

Question 4:
```
以本地关键路径为准：
必过：RTOS 启动、LVGL 初始化并渲染本地测试页、背光、触摸 I2C ACK、WiFi STA 连接并获取 IP、OTA 任务存活。
可降级：WebSocket 服务器连接/收到消息。服务器不可达不应回滚，否则会因云端故障把好固件标记为坏。设计一个 "minimum local UI" 显示设备状态，渲染成功后即可证明显示/触摸可用。
流程：启动后 30~60s 稳定运行且无复位；任何硬件/初始化失败触发 esp_ota_mark_app_invalid_rollback_and_reboot；远程服务失败只记录，不 fail。
```
Question 5:
```
可以，但有条件。作为 Secure Boot 前过渡，至少做到：
- manifest 签名（RSA/ECDSA，公钥内置）
- 固件 sha256 在写入 OTA 分区前校验
- 版本单调递增/禁止回退，min_version
- 防重放：manifest 带 issued_at/nonce，新鲜性校验
- HTTPS pinned CA
但注意：应用层校验不能防止通过 UART/JTAG 绕过 OTA 刷入自定义固件；它保护 OTA 通道。若直接使用 esp_https_ota 边下边写，sha256 校验会很别扭；可能需要先下载到 PSRAM/SPIFFS 临时区，验证后再 esp_ota_write。另一个折衷是下载后、重启前读回校验 sha256，但已写入 OTA 槽；若校验失败需将目标分区标记为 bad 或重下。建议封装自定义 OTA: http download → PSRAM/storage 临时文件 → manifest 验签 + SHA256 → `esp_ota_write`。
```

Now "最终结论: 方案是否可行？需要哪些修改？" We'll state: 可行但有条件；v0.1 不可直接用于生产。需要 modify as listed. Maybe table.

Need "补充任何被遗漏的关键点（如分区表、回滚时序、安全、功耗等）" We'll provide bullet list including:
- 分区表/存储布局: Need use LittleFS, maybe separate `nvs_ota`, ensure alignment and max app size. Provide suggested revised partition table maybe:
```
# Name,   Type, SubType, Offset,   Size,   Flags
nvs,      data, nvs,     0x9000,   0x8000,
otadata,  data, ota,     0x11000,  0x2000,
phy_init, data, phy,     0x13000,  0x1000,
factory,  app,  factory, 0x20000,  0x400000,
ota_0,    app,  ota_0,   0x420000, 0x400000,
ota_1,    app,  ota_1,   0x820000, 0x400000,
storage,  data, littlefs,0xc20000, 0x3E0000,
```
But note offsets: phy_init at 0x13000 then next app at 0x20000. Gap from 0x14000 to 0x20000 okay. But maybe phy_init data needs 0x1000 at 0x11000? It's fine. Need check if otadata at 0x11000 size 0x2000 ends at 0x13000; phy_init at 0x13000; end 0x14000; app at 0x20000. Gap 0xC000. okay.

If using Secure Boot v2, partition table offset must be 0x8000? yes.

Need mention "factory reset must erase/write otadata? Actually `esp_ota_set_boot_partition(factory)` writes otadata to point to factory. Need "factory reset" may also erase NVS credentials. Decide behavior.

- OTA resumption details: `esp_https_ota` may require `CONFIG_OTA_ALLOW_HTTP`? No.

- Server certificate:
```
cert_pem 应该包含 CA 证书，而不是叶证书；支持证书轮换：可以在 manifest 中下发新的 CA 公钥（但 manifest 本身要签名）或烧录时内置两个根证书。
```
- Power: Brownout, supply stability during flash write; if battery, do OTA only if sufficient charge; disable modem sleep during download to avoid connection drop; use `esp_wifi_set_ps(WIFI_PS_NONE)` during OTA then restore.
- Flash wear/resume: Don't write NVS every chunk; use periodic offset save or only on interruption.
- Logging/diagnostics: Save crash reason, boot count, OTA state to NVS/SPIFFS to diagnose rollback.

Need maybe mention "factory partition and Secure Boot: factory must be signed if Secure Boot; factory can be built with a minimal OTA-only firmware that connects and reflashes. This is a good production strategy."

Could include "推荐增设 `ota_status` NVS namespace to store last attempt result for telemetry."

Let's now write final answer.

Need maintain Chinese technical accuracy. Use terms:
- `esp_ota_mark_app_valid_cancel_rollback`
- `esp_ota_mark_app_invalid_rollback_and_reboot`
- `esp_ota_set_boot_partition`
- `esp_ota_get_state_partition`
- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`
- `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`

Need maybe mention "PENDING_VERIFY state and bootloader behavior" accurately. Let's verify if there is `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? I think yes but maybe not.
