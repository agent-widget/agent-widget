> Chinese version: [03-ota-design-evaluation.zh-CN.md](./03-ota-design-evaluation.zh-CN.md)

# 03-OTA Design Evaluation (deepseek-v4-pro)

> Date: 2026-08-22
> Evaluation model: deepseek-v4-pro
> Subject evaluated: 02-ota-design-esp-https-rollback.md

---

We need to respond in Chinese. We need to evaluate the ESP32 OTA design proposal. We need to list 3-5 severe defects/risks in order of severity, answer each of the 5 questions to be evaluated one by one, and give a final conclusion on whether the proposal is feasible or needs modification, supplementing omitted key points such as the partition table, rollback timing, security, and power consumption.

We need to evaluate strictly as a senior embedded firmware architect and ESP32 expert. We need to analyze the proposal carefully. Note the hardware: Waveshare ESP32-S3-Touch-LCD-3.5B: ESP32-S3R8, 8MB PSRAM, 16MB Flash. Use case: AI Agent Status display, WiFi + WebSocket, LVGL. During development, iterate quickly without serial flashing; in production, be reliable and brick-proof. Proposal: esp_https_ota + dual-partition Rollback + Secure Boot v2.

We need to find defects. Partition table: nvs 0x9000 size 0x6000, otadata 0xf000 size 0x2000, phy_init 0x11000 0x1000, factory 0x20000 0x400000, ota_0 0x420000 0x400000, ota_1 0x820000 0x400000, storage spiffs 0xc20000 0x3E0000. Check sizes and offsets. 16MB flash = 0x1000000. End of storage: 0xc20000 + 0x3E0000 = 0x1000000 exactly? 0xc20000 + 0x3e0000 = 0x1000000 yes. Good. But SPIFFS size 0x3E0000 = 4063232 bytes ~3.875 MiB. Okay.

Potential issue: phy_init partition? Usually phy_init size maybe 0x1000 okay. nvs size 24KB maybe okay but maybe too small if OTA resumption + WiFi? Could be fine. But OTA resumption uses NVS? esp_https_ota with ota_resumption maybe uses RTC? Need check. But okay.

Critical defect: No "ota_data_initial" or "otadata" must be data/ota? okay.

But they included factory plus two OTA app slots. In ESP-IDF with dual OTA partitions, factory is not used as an OTA slot, but the bootloader may select factory if otadata is invalid? The app can use factory as a fallback. However, with a partition table that has a factory app plus ota_0/ota_1, OTA may not be able to update the factory slot; esp_ota_get_next_update_partition usually returns ota_0 or ota_1, not factory. They intend factory as the "last-resort fallback," but how do you jump back to factory? Is there a mechanism? There is esp_ota_set_boot_partition(esp_ota_get_factory_partition())? The factory partition is type app, subtype factory. You could boot factory via a "factory reset" or if the OTA data is invalid? Actually bootloader behavior: if otadata says the OTA sequence is valid, it boots the OTA app. If the OTA data is invalid/corrupt, it boots factory. To intentionally jump to factory, you could call esp_ota_set_boot_partition(factory partition) then restart. But that needs a code path, and it is not in the described flow. Might be missing.

We need to identify severe defects.

Possible severe defects:

1. Rollback timeout / watchdog confusion: "Self-check fails/times out → hardware watchdog reset → bootloader automatically rolls back to the previous slot." But a hardware watchdog reset alone does not mark the app invalid. You need to explicitly call esp_ota_mark_app_invalid_rollback_and_reboot() if the self-check fails or times out. If the app crashes repeatedly before it can mark itself invalid, does the bootloader have a rollback counter? Actually CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE and CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT? Let's recall. In ESP-IDF, the rollback process: after an OTA update, the bootloader sets the new partition to PENDING_VERIFY and boots it. If the app calls esp_ota_mark_app_valid_cancel_rollback() it becomes valid. If the app calls esp_ota_mark_app_invalid_rollback_and_reboot() it marks itself invalid and reboots to the previous app. If the app crashes or never marks, does the bootloader have a "rollback" mechanism? Actually "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE" and "CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT" seconds? Hmm. Let's recall: there is a "rollback and anti-rollback" mechanism. Does the bootloader count boot attempts? Let's verify.

ESP-IDF OTA rollback: after a successful OTA, the new firmware boots. It has state PENDING_VERIFY. If esp_ota_mark_app_valid_cancel_rollback is never called, then after a reboot? Actually there is no automatic timeout in the app? Does the bootloader have a rollback counter? The bootloader checks otadata. If the partition is in PENDING_VERIFY and "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE" is set, the bootloader may attempt to boot it and monitor? I think the bootloader does not automatically revert just because the app didn't call valid. There is "app rollback" via `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? Does the rollback timeout only apply to anti-rollback? Let's recall precisely.

ESP-IDF OTA rollback: there are three functions:

- esp_ota_mark_app_valid_cancel_rollback()
- esp_ota_mark_app_invalid_rollback_and_reboot()

If new firmware boots and doesn't call valid, does the next reboot (e.g., due to crash) make the bootloader see PENDING_VERIFY? Actually `esp_ota_mark_app_valid_cancel_rollback` sets otadata to VALID. If not called, what state does the bootloader see? Maybe otadata has "new app" pending; the bootloader sets it to PENDING_VERIFY? Hmm.

I recall: the bootloader checks ota_data. The ota_state can be:

- Undefined (0xFFFFFFFF) for factory?
- New?
- Pending verify?
- Valid
- Invalid
- Abort?

The OTA data format has `ota_seq` and `ota_state`. When an OTA update writes a new image, it doesn't set the state? When booting a new image, the bootloader sets the state to PENDING_VERIFY in otadata. If the app calls valid, the state becomes VALID. If not, the state remains PENDING_VERIFY. On the next boot, the bootloader sees PENDING_VERIFY. What does the bootloader do? It probably boots the same image again (since there is no invalid mark), unless the app has called invalid. There is no automatic rollback on crash unless the app calls invalid. However, "rollback timeout" may exist in the bootloader: if `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` is enabled, can the bootloader monitor the app and revert if not valid after a timeout? Let me search my memory: there is `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` where the timeout is in seconds. In `bootloader_flash.c`, after booting an OTA app, if rollback is enabled, does the bootloader set a timer? Actually no, the bootloader doesn't run alongside the app. But there is a hardware RTC watchdog? Hmm.

Let's recall from the docs: "Rollback Process" in ESP-IDF. The bootloader uses `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` to enable rollback support. If it is enabled, after an OTA update and reboot, the new firmware is in PENDING_VERIFY state. The application must call `esp_ota_mark_app_valid_cancel_rollback()` to indicate it is valid. If the application fails to call this and reboots, will the bootloader mark the application invalid and roll back? Or if the application doesn't call it in time? There is a "rollback timeout," maybe `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`, used by the bootloader to wait for valid? Not possible, because the bootloader is not running. Wait, maybe the app's `esp_ota_mark_app_valid_cancel_rollback` is required; if not called, a reboot occurs after a panic. On the next boot, does the bootloader see the pending-verify state and roll back? Let's check: "ota_state" might be set to PENDING_VERIFY by the bootloader at boot time. If the app was previously PENDING_VERIFY and rebooted without marking valid, the bootloader can infer it failed and mark it invalid / roll back. Let's search my memory.

From the ESP-IDF OTA docs:

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

If the app crashes before checking state, it reboots and boots the same new app again with state PENDING_VERIFY. Can it check again? Maybe there is a boot loop if the crash happens during early init before marking invalid. So you need a watchdog or a bootloader rollback counter.

The doc: "If the application fails to call esp_ota_mark_app_valid_cancel_rollback() within a certain number of boot attempts, the bootloader will rollback to the previous application." There is a "bootloader rollback counter" maybe in otadata? Let's recall: is there `CONFIG_BOOTLOADER_OTA_DATA_ERASE`? Hmm.

I know there is "rollback and anti-rollback" in Secure Boot V2. Anti-rollback uses `CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK` and a security version. Does it do automatic rollback? Let's not risk too much. The described scheme says "self-check fails/times out → hardware watchdog reset → bootloader automatically rolls back to the previous slot." The hardware watchdog reset alone won't mark the app invalid. If the app is stuck, task watchdog reset -> reboot to the same PENDING_VERIFY app -> maybe the app gets stuck again -> boot loop. Unless the bootloader has rollback on PENDING_VERIFY after a timeout. Need to mention this as a risk: you cannot rely solely on the hardware WDT reset; you must call `esp_ota_mark_app_invalid_rollback_and_reboot()` explicitly or implement a boot attempt counter in NVS to mark invalid and roll back.

Let's verify exact ESP-IDF behavior. In `esp_ota_ops.c`, bootloader's `ota_ops.cpp`? There is `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` in the bootloader. If enabled, the bootloader checks `ota_state` and a "rollback counter" in `otadata`: is there `esp_ota_get_app_elf_sha256`? Actually I recall the bootloader has `bootloader_ota_get_rollback_counter` maybe. Hmm.

Let's search memory snippets: in ESP-IDF Kconfig.bootloader:

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

Wait, how does the bootloader enforce the timeout? Maybe it doesn't; maybe the app has to call the API; does the bootloader use an RTC timer? `esp_ota_mark_app_valid_cancel_rollback` writes to otadata. If not called within the timeout, the bootloader won't know until reboot? But maybe the bootloader can set a timer in RTC? Actually the bootloader cannot run after boot. Maybe the "timeout" is not real-time; the bootloader records the time at boot in RTC memory and the app's `esp_ota_mark_app_valid`? Hmm.

Let's locate the actual ESP-IDF doc from memory: the rollback process:

- The OTA update mechanism sets the OTA data to point to the new app with state "New"?
- At boot, if the state is "New," the bootloader sets it to "Pending Verify" before loading the app.
- If the app calls `esp_ota_mark_app_valid_cancel_rollback`, the state becomes "Valid."
- If the app calls `esp_ota_mark_app_invalid_rollback_and_reboot`, the state becomes "Invalid," and the bootloader chooses the previous app on the next boot.
- If the state remains "Pending Verify" and the device reboots (e.g., due to panic), the bootloader sees "Pending Verify" and will choose the previous app (rollback). That doesn't require the app to mark invalid. Actually yes, that's likely: if the bootloader sees state PENDING_VERIFY, it rolls back. But if the app is stuck (not rebooting), it won't roll back until a watchdog reset. Then on reboot, the bootloader sees PENDING_VERIFY and rolls back. So a hardware watchdog reset can lead to rollback if rollback is enabled and the state is still pending. But if the app calls `esp_ota_mark_app_valid_cancel_rollback()` and then later crashes, there is no rollback because it was marked valid. So the self-check must not mark valid until fully stable. That seems plausible. But what about the "no crash within 30 seconds" self-check; if the watchdog resets at 30s, the bootloader sees pending and rolls back. Fine. But what if the app hangs without a WDT? You need a task WDT. What if the app gets into a loop before starting the WDT? Early init: if the bootloader boots the app but the app crashes very early before enabling the task WDT, maybe there is no timeout; could it hang? The bootloader cannot know. But there is a hardware RTC WDT enabled? IDF default has a task WDT; maybe early boot has a panic. But if the app hangs in init before the task WDT? The RTOS scheduler starts and the idle task can watchdog? Usually the interrupt watchdog may be enabled. But mention it.

Still an issue: they say "self-check fails/times out → hardware watchdog reset → bootloader automatically rolls back," but you need to ensure bootloader rollback is enabled and the state remains PENDING_VERIFY; also the app must not call mark valid too early. Need to mention.

2. Flash size/partition offset issues maybe: ESP32-S3 16MB flash. Partition offsets 0xc20000 + 0x3E0000 = 0x1000000. Fine. But the partition table itself has a default offset of 0x8000? They start nvs at 0x9000. That leaves 0x1000 for the partition table? Could be okay (partition table offset 0x8000, size 0x1000? Actually the default partition table offset is 0x8000, max size 0xC00? The partition table usually starts at 0x8000 and ends before 0x9000 if nvs is at 0x9000. Fine. But there is no `otadata` initial? Fine.

Potential issue: `storage` SPIFFS at 0xc20000, size 0x3E0000. SPIFFS max size? Is SPIFFS on ESP-IDF deprecated? It's okay up to 4MB. But they mention fonts/resources. But if OTA updates the user app, does the SPIFFS storage persist? Yes. But if factory reset / app partitions, it is not erased. Could need asset versioning. But not critical.

Critical: the partition table with factory + two OTA app slots consumes 12MB of app slots + 4MB storage + NVS/otadata. But if they use Secure Boot v2 with a signed app, the app image size may increase due to the signature block? Max size? A 4MB slot is enough if the app is under 4MB. But with LVGL + fonts it could grow. They put fonts in SPIFFS, okay. Need to mention reserving space for the app due to OTA scratch? esp_https_ota writes directly to the OTA partition, so no scratch is needed. Fine.

3. Secure Boot v2 + OTA: they say "during development, use soft verification first (app-layer manifest signature verification), and hardware-enable before production release." But if using `esp_https_ota` with signed app images under Secure Boot v2, the OTA firmware must be pre-signed and maybe pre-encrypted? Secure Boot v2 requires the image to be signed with a private key, with the public key digest in the eFuse. But if the app is signed, the OTA binary must be the signed image (`.signed.bin`). The build script uses `esptool.py sign_data --keyfile signing.key build/app.bin` then copies app.bin to the server. But does the `sign_data` command sign data? Need to check. Secure Boot v2 uses an appended RSA-PSS signature block. The command should be `idf.py secure-build`? Actually standard: `esptool.py --chip esp32s3 secure_verify_key digest.bin`? Hmm. Maybe not major.

Potential issue: Secure Boot v2 and `esp_https_ota` — does the OTA code verify the signature itself if secure boot is enabled? The bootloader verifies at boot. The OTA code uses `esp_ota_ops` to write the image. It must ensure the image type and signature. Can `esp_https_ota` handle a signed app? It writes the entire binary. The bootloader verifies. okay.

But eFuse is irreversible: if they burn the Secure Boot key without the ability to boot an unsigned factory, and they have a factory partition that is maybe unsigned? Need to ensure all images in all slots are signed. Also "min_version anti-rollback" may be an issue. Need to mention.

4. Missing server-side manifest tampering: that is question 5. We can discuss.

5. OTA server SSL certificate: they embed the server root certificate. But if using a self-signed root, okay. Need to include the full chain and ensure the cert PEM is correct. But not severe.

6. OTA resumption and NVS usage: `ota_resumption` uses NVS to store the offset. With NVS size 0x6000 (24KB), if the device also stores WiFi + OTA states, it may be tight? Maybe okay but could use more. If using resumption, frequent NVS writes during download cause flash wear. Need to mention wear leveling and flash endurance. But maybe not severe.

7. Partial HTTP download and PSRAM: that is a question they ask. We can answer.

8. Development ArduinoOTA in Phase 1: they need to switch the partition table. ArduinoOTA uses the Arduino framework, maybe not ESP-IDF? The hardware is an ESP32-S3 with a touch LCD. They might use PlatformIO/Arduino. ArduinoOTA uses the `Update` class which can write to flash. The default Arduino partition scheme for ESP32-S3 may be "Default 4MB with spiffs," etc. If they use a custom partition table, they can configure `board_build.partitions` in PlatformIO. But if Phase 1 uses ArduinoOTA to flash a new sketch to the current app partition, it assumes the partition table maybe has app0/app1 but no factory? Arduino OTA can write to the OTA partition. Need detail. The boundary is at board support / partition table configuration. We can answer.

9. The self-check items for the display terminal: need to define what "pass" means. We'll answer.

10. Missing "factory reset" path: if both OTA slots are bad and factory exists, how do you boot factory? Need a mechanism. The partition table includes factory, but the app flow doesn't describe when to set factory. The bootloader will not boot factory automatically if the OTA data points to valid/invalid? Actually if ota_data is invalid, the bootloader boots factory. To recover from a bad OTA, the user can use a GPIO forced factory reset or an NVS flag. Missing. Also, if both OTA slots are bad, factory is vital. Need to provide a button/GPIO test to set factory and reboot, or have the app call `esp_ota_set_boot_partition(factory)` and reboot after multiple failures. Need to mention.

11. "Storage" SPIFFS and OTA rollback: if the new firmware expects new assets in storage but you roll back to the old firmware, the assets could be incompatible. Need to include asset versioning and migration; don't wipe storage on OTA unless necessary. Maybe mention.

12. Power: OTA download is power-intensive (WiFi + flash write). Need to ensure sufficient supply and no low voltage during flash write that could cause corruption. Use the brownout detector. Do they mention power? We need to supplement.

13. Watchdog/rollback timeout config: they say `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` default 5s can be increased. Need to confirm: it may not work as they think. Let's be careful. We can state: this Kconfig option is not a runtime app timeout; it is used by the bootloader? Actually maybe it doesn't exist. But they mention it. We'll advise clarifying.

Let's search my memory for the exact Kconfig. In ESP-IDF there is `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`; and maybe no separate timeout? I think there is `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? Hmm. The docs for "ESP-IDF OTA" say "The rollback process is triggered automatically if the application does not mark itself valid within a set time period. The set time period is configured using CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT." This indeed. But how does the bootloader enforce it? It may use the RTC timer and on next boot? Wait, the app could mark valid after the timeout. If it doesn't, next reboot rolls back. Is the timeout measured by the bootloader? Actually the bootloader runs before the app; there is no time. Hmm, maybe the app has an API that checks whether the timeout elapsed? Does the bootloader store a timestamp in RTC slow memory? On boot, if the state is pending, the bootloader could check the RTC time since last boot? No clock may not persist. It could use an RTC timer running during the app. If the app doesn't mark valid and then the WDT resets at the timeout, the bootloader sees pending and rolls back. But the "timeout" itself isn't a bootloader timer; it may be the app's responsibility to reset itself after the timeout via a timer. Maybe the Kconfig sets the timeout for `esp_ota_mark_app_valid_cancel_rollback`? Hmm.

Let's not overcommit. We can phrase: "Note that IDF's automatic rollback only triggers when, after the new firmware crashes / the WDT resets, the bootloader detects the state is still PENDING_VERIFY; if the code mistakenly calls mark_valid before the self-check, or hangs without producing a reset, there will be no rollback. You must explicitly set a self-check timeout timer, and the failure path must call `esp_ota_mark_app_invalid_rollback_and_reboot()`."

Also need to mention a boot attempt counter: if the new app crashes very early before app code runs, might the bootloader enter a boot loop across ota_0/ota_1? Maybe "bootloader rollback" has a rollback counter? We can mention implementing an additional NVS boot counter if not present.

Let's think of more severe flaws.

- "Development phase without serial flashing: ArduinoOTA," but later "Secure Boot v2" in production. Once Secure Boot v2 is enabled, you cannot use unsigned sketches or ArduinoOTA? Can ArduinoOTA flash a signed image? Actually Secure Boot verifies the app at boot; you can still OTA-flash if the image is signed? ArduinoOTA uses the Update class which writes to flash, but the bootloader will reject unsigned images if Secure Boot is enabled. Development before enabling is okay.

- "Transport: HTTPS + server certificate verification" with the `cert_pem` root certificate. But if using the `esp_https_ota` API and only setting `cert_pem` to the root CA, it verifies the server certificate chain. For a self-signed root, the server cert must be issued by that root. If you use the server cert directly in `cert_pem` (leaf), it may work if the server cert is self-signed. Need to ensure the CN/SAN matches the URL. Fine.

- "Integrity: esp_ota built-in image verification" — `esp_https_ota` does not verify the SHA256 from the manifest; it relies on the image header checksum and signature. The manifest `sha256` is not checked by the provided code. Need to check. If they intend to verify the manifest signature, okay. But the code example downloads latest.bin directly; the manifest just checks the version. The `sha256` field is not used. Need to mention: the manifest sha256 is not checked, so an attacker who can alter the manifest without changing the firmware could cause a downgrade? Actually HTTPS protects transport; what about server compromise? The application should verify the manifest signature and SHA256. The flow says "fetch manifest.json → version > current → esp_https_ota downloads to the free partition," with no signature verification. If they defer Secure Boot, any server compromise or DNS hijack with a valid cert? The cert is pinned. But they should still verify the manifest signature and firmware SHA256 before writing to flash. That's important. They mention "soft verification during development (app-layer manifest signature verification)" but not in the flow. So a critical gap: manifest/firmware application-level verification is missing in the design; it relies solely on transport and optional secure boot. If using HTTPS only, the server cert protects in transit but not from server compromise, a malicious CI build, or a misconfigured server. We can highlight.

- `esp_https_ota` writes to the *next update partition* directly. If `spiffs` storage is on the same flash, could power loss during an OTA write corrupt flash? But dual partition protects the current app; only the target partition is corrupted. But flash erase/write may affect power. Need to mention brownout.

- "factory fallback" — but if both OTA partitions become invalid? The bootloader selects factory if otadata is invalid. But `esp_ota_mark_app_invalid_rollback_and_reboot` marks the selected OTA invalid and chooses the previous one. If the previous is also invalid, maybe it falls back to factory. But not explicit.

- "anti-rollback via security version" — if they use Secure Boot v2 anti-rollback, the device could brick if the security version is set incorrectly and the manifest min_version is not aligned. Need to mention.

We need to sort by severity. Which are most severe?

Let's list possible defects:

A. The rollback self-check state machine has a fatal misunderstanding / does not implement an explicit failure mark; a hardware watchdog reset does not guarantee rollback and can cause a boot loop. (Severe)

B. Missing application-layer closed loop for manifest signature verification and firmware SHA256 verification; `sha256` is just decoration; without Secure Boot in development, only HTTPS transport is relied on, which cannot prevent tampering/server-side errors. (Severe)

C. The factory fallback is not implemented: no GPIO/command trigger to boot factory, no OTA failure-count limit, no way to switch the boot partition; the partition table has factory but the flow doesn't use it. (Severe/High)

D. Secure Boot v2 development/production switch and irreversible eFuse risk: not enabled in development, but before production the full signature test, signing of all app slots, and factory signing must be complete, otherwise enabling bricks the device; and eFuse burning is irreversible, with no clear key management/backup/device-batch policy. (High)

E. Partition table/NVS sizes and OTA resumption wear: NVS 24KB may be tight; OTA resumption frequently writes NVS causing flash wear; SPIFFS 4MB may be insufficient to store complete LVGL fonts/images? Maybe not most severe. Could be lower.

F. OTA URL/server certificate management lacks an updatable mechanism: the built-in root certificate is fixed; if the certificate expires or the server changes, it cannot be remotely updated? They could update via OTA. But once cert pinning is baked in, you cannot update the root cert without an OTA signed by the old one. Need to include. Could be medium.

But they asked for 3-5 most severe. We'll choose 5.

Let's think more deeply about ESP-IDF rollback: the described self-test items "no crash within 30 seconds of startup (task watchdog as backstop)" but they also include "display initialization," etc. If the app's task watchdog is not properly initialized/feeding before LVGL init completes, false rollback. Need a design.

Another critical issue: the OTA flow says "download complete → verify (signature/hash) → esp_restart()." But `esp_https_ota` internally already verifies the image header and signature? If using Secure Boot, the bootloader verifies at the next boot. The app-level "verify" before restart is ambiguous. For Secure Boot v2 no app-level signature verification is needed; for soft verification, need to use `esp_ota_verify`? There is no public API to verify the signature in the app? They could use `esp_ota_ops` to compare digests. Need not dwell.

Another issue: "ota_resumption = true" and "resume offset stored in NVS": does `esp_https_ota` with `ota_resumption` actually support resuming across reboots? It stores the pause offset in NVS? Actually the `ota_resumption` field in `esp_https_ota_config_t` may be supported since IDF V5? The API has an `ota_resumption` bool. It may use NVS. Need to ensure the custom NVS partition is accessible and large enough. It's a high-level feature. Could be okay.

Another issue: using SPIFFS for fonts/resources and OTA. SPIFFS is deprecated in favor of LittleFS/FatFS. But not severe.

Potential issue with `phy_init` data at 0x11000. On ESP32-S3, does `phy_init` need to be at 0x11000? yes. Size 0x1000 okay.

Potential issue: Secure Boot v2 with 16MB flash and DIO/DOUT? Not relevant.

Potential issue: OTA trigger from a background task. If the device is a status display, an OTA download could degrade WebSocket/LVGL performance. Need to schedule: check for updates only when idle, cap the download rate? Not severe.

Potential issue: "no-serial-flash fast iteration" via ArduinoOTA in Phase 1 makes sense, but if using LVGL + PSRAM and a custom partition, might ArduinoOTA not handle 16MB? It does. The transition to an IDF custom partition table could require one full serial flash. We'll answer.

We need to answer the 5 questions:

1. ArduinoOTA vs esp_https_ota: do we need to switch the partition table? Where is the boundary?

- ArduinoOTA (Arduino-ESP32) uses the same ESP-IDF OTA mechanism? Does the ArduinoOTA library use the `Update` class writing to `U_SPIFFS`? Actually ArduinoOTA uses `Update.begin` writing to flash. It can use the current active OTA partition? Let's recall: ArduinoOTA on ESP32 can update the sketch and filesystem depending on the command. It uses `esp_ota_get_next_update_partition` and writes to it. The partition table can be custom; if the custom table has ota_0/ota_1, ArduinoOTA will work. It doesn't know about factory perhaps. The main boundary is not the OTA mechanism but the partition table and bootloader config. If Phase 1 Arduino uses the default Arduino partition (maybe `default.csv` with ota_0/ota_1, maybe no factory), switching to a custom IDF partition table with factory+ota+spiffs requires reflashing the partition table and likely the full firmware because the partition layout changes. They can use the same custom partition table from the start in Phase 1. In Arduino/PlatformIO, set `board_build.partitions = custom.csv` and ensure "Flash Size 16MB" and "Partition Scheme Custom". Then ArduinoOTA will write to ota_0/ota_1. When moving to esp_https_ota, you can reuse the same partition table and bootloader rollback config. But if the ArduinoOTA library does not understand rollback marking, it may not call `esp_ota_mark_app_valid_cancel_rollback`, leaving the app PENDING_VERIFY forever. Thus if Phase 1 uses bootloader rollback enabled, every ArduinoOTA update may roll back after reboot. That's important: ArduinoOTA may not mark the app valid. Need to check: Arduino's `Update.end` may not call `esp_ota_mark_app_valid_cancel_rollback`. The default Arduino bootloader doesn't use rollback? If CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not enabled in the Arduino SDK, then no issue. But if using a custom IDF bootloader with rollback, ArduinoOTA may need modification. So the boundary includes the bootloader rollback configuration. If using Arduino's precompiled bootloader with rollback disabled, fine. For Phase 2, you need a rollback-enabled bootloader and self-check. So the transition: keep the same custom partition table; but the bootloader may need to be flashed from an IDF build, and the application must call mark valid. Also Phase 1 ArduinoOTA uses unsigned OTA over bidirectional TCP (not HTTPS); not suitable beyond the LAN. No server required.

2. Impact of Secure Boot v2 on debugging (JTAG, serial logs), and how to minimize it?

- Secure Boot v2 doesn't encrypt flash; it only verifies the app. It doesn't block UART logging by itself. JTAG debugging may be restricted if `CONFIG_SECURE_BOOT_ALLOW_JTAG`? Actually Secure Boot may disable JTAG if the eFuse `JTAG_DISABLE` is set separately. By default, enabling Secure Boot doesn't necessarily disable JTAG? Need to verify. On the ESP32-S3, the `JTAG_DISABLE` eFuse can be burned. Secure Boot V2 may not require disabling JTAG. But for production you may choose to disable it. To minimize: do not burn `JTAG_DISABLE`; do not enable Flash Encryption; keep UART ROM messages? Secure Boot may block boot if unsigned, but after boot the OS log still works. Use `CONFIG_SECURE_BOOT_ALLOW_ROM_BASIC`? There is `CONFIG_SECURE_BOOT_ALLOW_JTAG`? I'd say:

  - Secure Boot v2 only checks the image signature at boot. It does not need Flash Encryption, so UART logs remain available.

  - JTAG may remain available if the `SECURE_BOOT_ENABLE` eFuse is set but `JTAG_DISABLE` is not burned. However, some security features like "Disable JTAG" can be independently burned. To optimize development, keep `CONFIG_SECURE_BOOT_ALLOW_JTAG` enabled and don't burn the `JTAG_DISABLE` eFuse until final production.

  - But if you enable Secure Boot during development, you must sign every build. That complicates rapid iteration. Recommended: development builds remain unsigned; Secure Boot is enabled only on a dedicated "secure build" test device, not on all development boards. Separate eFuse lifecycle.

  - Also Secure Boot V2 may require `CONFIG_SECURE_BOOTLOADER_MODE` and a public key. You can maintain a "dev key" and burn it only on a few devices. The production key must be generated offline and stored in an HSM.

  - Use `esp_secure_cert`? No.

3. With 8MB PSRAM, is partial_http_download worth it? Buffer strategy?

- The AI Agent display app likely has firmware <4MB, maybe small. `esp_https_ota` by default uses a RAM buffer? `esp_https_ota` downloads to flash directly via `esp_ota_write`, using a 4KB buffer in internal RAM. PSRAM is not required for OTA. Partial HTTP download is an optimization for huge images to avoid timeouts and reduce memory; with 8MB PSRAM you could allocate a larger buffer (e.g., 16-32KB) in PSRAM, but PSRAM is slower and there are cache considerations. It's generally not needed for <4MB. The OTA write speed is usually limited by flash erase/write and network, not buffer size. Use `partial_http_download` if you need to download over unstable connections or show progress with range requests; but it adds complexity: the server must support Range. For this device, not necessary. If used, buffer in internal RAM 4-8KB; avoid a large PSRAM buffer because OTA writes may call flash operations while the PSRAM cache is disabled? Actually flash writes require the cache to be disabled; a buffer in PSRAM may be inaccessible. So use an internal RAM buffer. Recommendation: skip partial_http_download; keep `ota_resumption` for unstable networks.

4. For a weak-interaction app, what counts as passing the rollback self-check?

- The app needs to prove it can perform its core function: boot, read config, connect to WiFi, establish a WebSocket connection, receive/parse at least one status message, render it to LVGL successfully, and respond to touch input. Since there is no sensor, the self-check should include:

  a) System startup successful: `esp_ota_get_state_partition` returns `ESP_OTA_IMG_PENDING_VERIFY`.

  b) Peripherals: LVGL display init, backlight on, touch controller I2C ACK, read version/status.

  c) Network connectivity: WiFi connects to the configured AP and obtains an IP; DNS resolution for the OTA server perhaps.

  d) Application service: the WebSocket client connects to the broker/server; receives a valid status message within the timeout (or at least subscribes). Maybe if the server is not available, do not fail the rollback? Need to consider. For an "AI Agent Status display," if the server is temporarily unavailable, marking invalid would cause an unnecessary rollback. So the self-test should distinguish device-local failures (display/touch/WiFi hardware) from remote/service failures. WiFi can connect but the WebSocket server may be down; that's maybe not firmware-invalid. So required self-check: display + touch + WiFi station connection + OTA task alive. The WebSocket connection/render test should be soft: if no remote message, render a local test screen and still pass; log a warning. Do not roll back due to a temporary cloud/agent outage. But the design should have a "minimum viable local UI" always available.

  d) Version self-report: the app_desc version matches the manifest.

- Pass criteria: all critical hardware/peripheral init passes; the network stack is up; a local test pattern is rendered; a timer feeds the WDT. Mark valid only after N seconds of stable operation (e.g., 30-60s) without reboot. If any critical item fails, explicitly mark invalid and reboot.

- Need to mention "watchdog feed must be active during LVGL/test; avoid false rollback".

5. manifest.json signature as a transitional scheme before Secure Boot?

- Yes, but only if done correctly. It provides application-layer authentication/version policy; it does not protect against local malicious firmware that bypasses the OTA app. If an attacker can flash via UART/JTAG or replace the firmware, the manifest signature doesn't help. It protects the OTA channel against server compromise/active network attacks if you verify:

  - the manifest has a `sha256` of the firmware;

  - the manifest itself is signed (RSA/ECDSA) with a public key embedded in the app;

  - timestamp/nonce/anti-rollback? To prevent replay/downgrade, include `version`, `min_version`, `issued_at`, and possibly a `nonce` from the device? But the device clock may not be reliable. At minimum verify the signature and version monotonicity using the app's stored last-accepted version. The manifest signature is a good transition if the firmware image is not Secure Boot-signed; you can compute the SHA256 of the downloaded image before flashing and compare. But if using `esp_https_ota` to download directly to flash, it writes as it downloads; so to verify SHA256 first, you need either to download to a temp buffer/PSRAM or a file, not write directly to the OTA partition, or use an API that verifies after writing but before reboot and can mark invalid. For 4MB firmware, can you hold it in RAM? 8MB PSRAM may be able to hold 4MB, but memory fragmentation/PSRAM may be okay? Better to download to an unused area? Could use `esp_https_ota` to write to the OTA partition; then after download, read back and compute SHA256? This is time-consuming and if it's bad you still need to mark invalid and revert? But if the invalid image is in the OTA partition and you don't reboot, the current app is still running. You could verify the hash after download, but the image has been written; if bad, can you call `esp_ota_set_boot_partition`? Actually you can mark that OTA partition invalid? `esp_ota_mark_app_invalid_rollback_and_reboot` only applies to the running app. Better to use `esp_https_ota` with `bulk_flash_erase` and then verify? Not necessary. Alternative: download the firmware to SPIFFS storage first (if space permits), then verify SHA256 and use `esp_ota_ops` to write to the OTA partition. But that's dual-copy flash wear. With 8MB PSRAM, you could allocate a 4MB PSRAM buffer to store the image, compute the hash, then write to OTA via `esp_ota_write`. But due to cache constraints maybe internal RAM? Write from PSRAM to flash? `esp_ota_write` can copy from PSRAM. Might be okay but the memory is large. Simpler: use the `manifest.json` signature and rely on HTTPS for transport; just check version and size. Can hash verification be implemented by `esp_https_ota` with `http_config.buffer_size`? Not.

Maybe answer: yes, as a transition, but not sufficient; require firmware SHA256 verification and manifest signature; you can use `mbedTLS` to verify the signature. If using `esp_https_ota`, can you set `http_config` to download into a buffer? Hmm. The better approach: build the OTA image as a custom `.bin` containing an embedded manifest? Or use the `advanced_https_ota` example with `esp_https_ota_begin` / `esp_https_ota_perform`? It still writes on the fly. To check SHA256 before writing to OTA, you may need a custom download-and-write.

Maybe mention: "In order to be truly tamper-proof in the no-Secure-Boot phase, you cannot rely only on HTTPS; manifest signature + firmware sha256 is necessary but not sufficient. Best implemented as: HTTPS download to temporary storage (PSRAM or SPIFFS) → verify signature → verify hash → then `esp_ota_write` to the target partition."

Now the final conclusion. Need to decide if the scheme is feasible. It is overall feasible with modifications. Need to say "the overall direction of the scheme is feasible, but the current v0.1 design cannot be used directly for production." Need to list the modifications: fix the rollback state machine; add an app-level verifier; implement factory fallback; clarify Secure Boot enable/lifecycle and key management; adjust partition/NVS; perhaps include encrypted flash? Not needed but maybe optional. Need to mention: if the device displays status via WiFi + WebSocket, flash encryption may not be necessary unless the data is sensitive. But Secure Boot alone is not enough for confidentiality; however that is not the purpose here.

Need to provide additional omitted key points:

- Partition table: include `erase_size`, alignment? They are mostly aligned. Need to include `ota_data_initial`? Not needed.

- Rollback timing sequence: need to understand the exact bootloader sequence: after reboot, the bootloader sees PENDING_VERIFY and chooses the previous app; the app must not mark valid too early. The self-test must start after critical init. Include `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`? Need to mention: if using the "rollback timeout" config, the app still must explicitly mark invalid or reboot. Also need to test rollback before production.

- Security: Secure Boot V2 alone verifies source but doesn't encrypt. Consider Flash Encryption for protecting Wi-Fi credentials and assets. But Flash Encryption + OTA requires pre-encrypted images or NVS encryption. Could complicate. If the device stores credentials in plaintext, a local attacker can read them via a UART flash dump? Actually flash encryption prevents that. But maybe not necessary for this use. Mention as optional.

- OTA server certificate renewal: implement certificate rotation or dual roots? Because `cert_pem` is hard-coded. Need an OTA app update path for a new cert. Could include a future root cert in the manifest? Not critical.

- Power: brownout detector and stable 3.3V. During OTA flash writes, supply current spikes; use sufficient capacitance. Avoid OTA while the battery is low; check voltage before OTA.

- Flash wear: OTA resumption in NVS may cause wear; use LittleFS instead of SPIFFS? NVS has wear leveling, yes. OTA update frequency is likely low. Need to write only when necessary.

- Logging: preserve logs during rollback; write the crash reason to NVS to diagnose.

- Testing: need to test power loss at every step of OTA (erase, write, post-signature), test rollback with both good and bad images, test factory fallback, test server down/throttle.

Need maybe mention "esp_https_ota with `cert_pem` root CA and `ota_resumption` is okay, but the manifest URL should be versioned and not latest.bin? latest.bin with a manifest is fine."

Now write the report in Chinese.

Need a structure:

- Evaluation summary

- 1. Severe defects/risks (sorted by severity)

  1. Fatal flaw in the rollback self-check/watchdog rollback timing

  2. Missing application-layer OTA verification; the manifest sha256 is decoration; not trustworthy during development without Secure Boot

  3. The factory fallback has no execution path; cannot actually recover to factory

  4. Insufficient Secure Boot V2 / eFuse lifecycle management; enabling in production may brick the device

  5. Partition/NVS/OTA resumption design has resource and wear risks (or a fixed server certificate lacking rotation)

- 2. Answers to the five questions

- 3. Overall conclusion and required modifications

- 4. Supplementary omitted key points

Need to ensure it's not too long? Desired oververbosity is 5, but the user requested a complete report. We can be thorough.

Let's craft the details.

Detailed point 1:

"The scheme attributes self-check failure/timeout to an automatic bootloader rollback after a hardware watchdog reset. This understanding is incomplete. IDF rollback depends on the otadata state. If you already called mark_valid during the self-check, a failure cancels the rollback. If the system hangs and the watchdog does not reset, there is no rollback. If crashes happen repeatedly early in app startup and the bootloader has not enabled rollback / otadata is mishandled?" Need to be precise.

Let's phrase:

- ESP-IDF's `esp_ota_mark_app_valid_cancel_rollback()` is an active application-side mark. If a hardware WDT reset happens after user code has already called `mark_valid`, a later self-check failure will not trigger a rollback.

- If the self-check timeout just "waits 30 seconds" without explicitly calling `esp_ota_mark_app_invalid_rollback_and_reboot()`, the state stays PENDING_VERIFY, and the next reset may boot the same new firmware again, forming a boot loop.

- If the app crashes early without triggering a WDT (e.g., interrupts disabled, hang before the OS starts), no reset may occur, the device stalls, and there is no rollback.

- Therefore the risk is: the design treats the "watchdog reset" as the rollback trigger, but in reality the software state machine must explicitly mark invalid, or the bootloader rollback option must handle PENDING_VERIFY correctly. You need to call `esp_ota_mark_app_invalid_rollback_and_reboot()` in the self-check timeout handler, together with `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` and a "boot failure counter." Also be careful not to call mark_valid too early.

Let's be exact: "bootloader automatic rollback" actually may happen if the state is PENDING_VERIFY on reboot. But the user code may need a hardware WDT to cause the reboot. We can state: "the hardware WDT reset only produces one reboot; whether rollback actually happens depends on the bootloader seeing otadata = PENDING_VERIFY; this requires rollback to be enabled in the bootloader. If the app calls mark_valid after a self-check failure, or does not reset for a long time, rollback cannot be guaranteed." That's safe.

Point 2:

- The manifest flow doesn't validate the manifest signature or the firmware SHA256. The shown code uses `esp_https_ota` directly against latest.bin. If Secure Boot is not enabled in development, the attack scenario: a malicious/compromised server or a MITM with a fake cert? HTTPS root pinning prevents MITM, but if the server is compromised or there is an insider threat, firmware could be pushed that passes transport and image checksum but is not authorized. The manifest sha256 is not checked, so a corrupted file could be flashed? Actually the image header checksum catches corruption; but malicious content could be flashed.

- Need application-level public-key signature verification for the manifest and the firmware hash. This is essential until Secure Boot v2 is enabled. In production with Secure Boot v2, the bootloader will verify the signature, but the manifest signature still helps version policy and avoids downloading malicious files? Actually Secure Boot only applies at boot; a malicious image written and then rebooted → the bootloader rejects it, but now the device boots the old app? Could be possible to roll back. Good.

- Severity: high.

Point 3:

- The factory partition exists but there is no description of how to boot it. Need to add:

  - A factory reset service: hold a touch button during boot, or call `esp_ota_set_boot_partition(esp_ota_get_factory_partition())` then reboot.

  - After N failed OTA attempts / rollback loops, automatically fall back to factory.

  - Ensure the factory app is also signed if Secure Boot is enabled and can operate.

- Otherwise factory is dead weight.

Point 4:

- Secure Boot v2 lifecycle:

  - eFuse is one-time; it cannot be reverted. Enabling it on production hardware without staged validation can brick the device.

  - Need to generate and store signing keys securely; if the key is lost there is no future OTA.

  - Must sign factory, ota_0, ota_1 — all images; if factory is unsigned, fallback is impossible.

  - Need to define how debug devices with Secure Boot disabled can be updated to Secure Boot enabled? It cannot be enabled via OTA; it requires physical access to burn the eFuse and flash a signed bootloader.

  - Need separate development and production keys; test on sacrificial units; have a "pre-production" phase with the production key but no anti-rollback until sure.

  - Need to consider that the anti-rollback security version and manifest min_version can themselves brick the device if set too high.

Point 5:

- Resource/wear:

  - NVS 24KB may be too small for WiFi + OTA resumption + rollback counters. If using ArduinoOTA, NVS may also be used. Need to calculate. Increase to 0x8000 or 0x10000 if offsets allow? Could adjust. But currently nvs ends at 0xf000; otadata is at 0xf000. If you increase NVS to 0x8000 (32KB), then otadata would be at 0x11000? But phy_init is at 0x11000. That would conflict. We can revise the partition table:

    ```
    nvs 0x9000 0x8000 (32KB)
    otadata 0x11000 0x2000
    phy_init 0x13000 0x1000
    ...
    ```

    But partition offsets usually don't need to be contiguous? They can be. You could increase NVS to 0x8000 ending at 0x11000. otadata 0x11000, phy_init 0x13000. Then the app offset could still be 0x20000. That works. Or use a separate `nvs_ota` partition for OTA resumption. Simpler.

  - `ota_resumption` uses NVS to store the resume state; each flash write is wear. If OTA is frequently interrupted, repeated writes occur. NVS has wear leveling but it's still finite. 24KB is small. Could store the offset only on pause, not every chunk.

  - SPIFFS is deprecated; 4MB is okay but consider LittleFS. Also, storing assets in SPIFFS: if the app version changes and assets change, you need an asset version manifest and maybe download assets separately? Not in scope.

Alternative severe risk: server root cert pinning. We can mention it as an "other important risk" rather than in the top 5.

Need maybe include: "the partition table with a 4MB factory slot plus two 4MB OTA slots plus 4MB storage works; but the max OTA app size is 4MB minus the signature block. Ensure the app with LVGL fits; if not, adjust. With 8MB PSRAM you might embed fonts in flash; but the 4MB slot limit is okay."

Now answer the questions thoroughly.

Question 1:

- It's the partition table and bootloader config that form the boundary.

- ArduinoOTA with the ESP32 Arduino core uses the same OTA partition mechanism. If you build Phase 1 with the Arduino core and a custom partition CSV with factory/ota_0/ota_1/spiffs, ArduinoOTA can OTA to ota_0/ota_1 without a partition change. Need to ensure the Arduino core's board options: Flash Size 16MB, Partition Scheme "Custom" pointing to the same CSV. Which bootloader? If you need rollback enabled, Arduino's precompiled bootloader may not have `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`. In that case you must build the bootloader from ESP-IDF with the same partition table and rollback enabled, then flash it once. Phase 1 may not need rollback? But to keep things consistent, use the same custom partition table from day 1. If not, when switching from the Arduino default to the IDF custom table, you need a one-time full serial flash (bootloader + partition table + app + filesystem) because the offsets change.

- The OTA protocol difference: ArduinoOTA is not HTTPS; it is a proprietary TCP OTA and not secure. It is fine on an isolated development network only. It may not call `esp_ota_mark_app_valid_cancel_rollback` if rollback is enabled. Either disable rollback in Phase 1 or patch ArduinoOTA/`Update.end` to mark valid. So the boundary: security, rollback semantics, bootloader, partition table.

- Recommendation: use the same custom partition table from the start; use ArduinoOTA only for rapid iteration in Phase 1 with rollback disabled, but flash the IDF bootloader and set the partition table once at the beginning. Phase 2 switches to esp_https_ota without partition table changes.

Question 2:

- Secure Boot V2 does not disable JTAG/serial logging by default; but it may restrict boot for unsigned code. It's possible to keep JTAG if you don't burn the `JTAG_DISABLE` eFuse and keep `CONFIG_SECURE_BOOT_ALLOW_JTAG`? Need to be careful: is there `CONFIG_SECURE_BOOT_ALLOW_JTAG`? Actually there is `CONFIG_SECURE_BOOT_ALLOW_ROM_BASIC`, maybe irrelevant. I'll phrase:

  - Do not burn the `JTAG_DISABLE` and `DISABLE_DL_DECRYPT`/`DISABLE_DL_CACHE` eFuses during development.

  - Use a dedicated "Secure Boot enabled but debug-friendly" test board; do not enable Secure Boot on all development boards. You can't disable it once the eFuse is burned, but you can choose not to burn it on dev units.

  - Keep serial logging enabled; Secure Boot V2 does not require disabling UART. But if Flash Encryption is enabled, it also doesn't block logs. However, Secure Boot v2 is often combined with flash encryption; that can complicate JTAG and core dumps. For debugging firmware logic, do it before burning the production Secure Boot key. For Secure Boot testing, use a separate device.

  - To minimize build pain: use a "dev key" generated locally for Secure Boot, sign automatically in CI, and flash via UART. Keep the production key in an HSM/offline.

  - Also ensure `idf.py openocd`/JTAG works with Secure Boot enabled if the eFuse doesn't disallow JTAG.

Question 3:

- `partial_http_download` is not necessary. The firmware image is probably <2-3MB; 8MB PSRAM doesn't automatically make it beneficial. `esp_https_ota` writes to flash through internal buffers; partial download is for very large images >4MB or unreliable links requiring Range.

- If used, use an internal RAM 4-8KB buffer; avoid placing the OTA write buffer in PSRAM because the flash cache disabled during writes may make PSRAM inaccessible. But maybe the ESP32-S3 has cache coherency? Still, internal RAM is safer.

- Better strategy: enable only `ota_resumption`; use event callbacks to throttle/UI progress. Do not enable partial_http_download unless tests show HTTP timeouts or memory issues.

Question 4:

- Define "local critical pass" vs "remote service pass":

  - Must pass: boot without crash, LVGL display init and renders a local test screen, touch controller responds to an I2C read, WiFi STA connects and obtains an IP, OTA task created.

  - Should not cause rollback: WebSocket server unavailable, no agent message, timeout to remote service. Reason: the firmware update may be fine but the server is down; rolling back doesn't fix that.

  - Could mark valid after local critical passes + a stable run timer (e.g., 60s) and optionally one successful remote update/status message if available within the window; if remote is not available but local passes, log a warning and still mark valid.

  - The version self-report should be checked from `esp_app_get_description()` at boot.

  - The app should have a "safe mode" local status page to verify display/touch when network/server are absent.

Question 5:

- Yes, as a transition, but it requires:

  - Sign the manifest with RSA/ECDSA using an embedded public key.

  - Include the firmware SHA256 in the manifest and verify the downloaded image hash before committing to the OTA partition. That may require downloading to temp/PSRAM/storage first.

  - Include anti-rollback: version > current, monotonic stored in NVS, min_version, timestamp/nonce to prevent replay (though a timestamp needs a secure clock; NTP may not be secure; at least a server-signed timestamp).

  - Use HTTPS with a pinned cert plus the manifest signature. Without Secure Boot, a local attacker with UART/JTAG can still flash arbitrary firmware. So it is not equivalent; it only protects the OTA channel.

- Once Secure Boot v2 is enabled, the manifest signature remains useful for server-side release policy and version control, but it is not mandatory for integrity if all apps are signed. Still recommended to check sha256/version before downloading.

- Need to mention "the manifest JSON itself can be subject to rollback/replay; use `issued_at` and reject old manifests."

Now the final conclusion:

- The direction is correct, but v0.1 has critical defects and cannot go directly to production / Phase 2.

- Must fix before design freeze:

  1. Rewrite the rollback state machine (explicit invalid mark, boot attempt limit, test).

  2. Implement application-layer manifest+firmware verification if Secure Boot is deferred.

  3. Add the factory fallback execution path and test.

  4. Formalize the Secure Boot key/eFuse lifecycle.

  5. Adjust partitions/NVS and evaluate wear.

- Then it is feasible.

Supplement omissions:

- Factory reset/recovery trigger.

- Asset/SPIFFS versioning and migration.

- Bootloader/log/crash diagnostics in NVS.

- Test plan: power-loss injection at each OTA phase; rollback test; downgrade/replay test; certificate expiry/rotation.

- Power/brownout: check VBAT/5V stability; brownout detector; do not start OTA on low battery or high temperature.

- Flash wear: OTA frequency; NVS writes; SPIFFS wear.

- Server: use versioned immutable artifacts, not a mutable latest.bin over time; use the manifest as a pointer; back up previous releases.

- Network: the OTA background task should not starve LVGL/WebSocket; set WiFi power save carefully during OTA download; keep the connection stable; maybe disable sleep during OTA.

- Security: if the device stores sensitive AI agent status data, consider Flash Encryption. At minimum encrypt NVS keys.

Need maybe include "the esp_https_ota server cert `cert_pem` root CA must be valid; if the server cert rotates, you need an OTA to update the root. Could include two root CAs in the certificate bundle? Does `cert_pem` support a bundle? `esp_http_client` supports a PEM with multiple certs? May be okay. Mention."

Let's write the final report in Chinese.

But before the final report, let's make sure there are no other hidden severe issues. The user requested specifically "3-5 most severe defects/risks (sorted by severity)" — we'll list 5. Need to make sure they are not too generic. We'll produce.

Let's maybe include a table at the top for the summary.

Now the format.

Potential phrases:

"1. Unreliable rollback timing / watchdog-triggered rollback design (fatal)"

Details:

```
The current design treats a hardware WDT reset as equivalent to triggering a rollback. In reality:
- The key to IDF OTA rollback is the state in otadata. After the self-check passes, you must call esp_ota_mark_app_valid_cancel_rollback(); on failure you must call esp_ota_mark_app_invalid_rollback_and_reboot().
- If the self-check timeout just "waits 30 seconds" without explicitly marking invalid, the state remains PENDING_VERIFY. After a watchdog reset, whether the bootloader rolls back depends on whether rollback support is enabled; even if it is, it is because the state never became VALID, not because of the watchdog itself.
- If mark_valid is mistakenly called during the self-check, later crashes/WDT resets will not roll back.
- If the app hangs before the watchdog is enabled, the device never resets, so it certainly never rolls back.
```

Need confirmation: if the bootloader sees pending verify, it boots the previous app after a WDT reset. That's true I think. We'll phrase: "In general, with rollback support enabled and the state still PENDING_VERIFY, the bootloader selects the previous slot after the next reset; but explicit handling is still required." Good.

"Recommendation: implement an `ota_self_test_task` that sets `ota_self_test_result` before the timeout; call mark_valid or mark_invalid; enable the task WDT and RTC WDT; never call mark_valid before the self-test completes. Add an NVS boot-failure counter; if the same new firmware enters PENDING_VERIFY N times in a row without passing, force mark invalid or fall back to factory."

Let's include it.

Second: "Missing application-layer verification; manifest.sha256 is decoration"

```
Without Secure Boot during development, the design relies only on the HTTPS cert_pem. HTTPS only guarantees the transport channel; it cannot guarantee that the server's content itself is trustworthy. manifest.json is unsigned and its sha256 is never verified. If the server is compromised, a CI artifact is replaced, or the DNS/SSL certificate is misconfigured (e.g., mistakenly trusting a public CA), the device may flash malicious or wrong firmware. Even if the bootloader rejects it, this causes a rollback/service degradation.
```

Actually a cert_pem rooted private CA prevents public CA. But server compromise remains.

Need to mention: "esp_https_ota's internal image check is only format integrity; it does not verify authorship and cannot replace a signature during development."

Third: factory fallback not implemented:

```
The factory partition is the last-resort fallback in the partition table, but the flow has no `esp_ota_set_boot_partition(factory)` or factory reset logic. The bootloader will not automatically return to factory just because both ota_0/ota_1 failed; you need to detect consecutive rollback counts or a button interrupt at the application layer and switch explicitly.
```

Need maybe: "if otadata is invalid, the bootloader will boot factory, but you can't rely on corruption." Good.

Fourth: Secure Boot eFuse lifecycle:

```
eFuse is irreversible; before enabling, you must confirm all bootable slots are signed. If factory is unsigned, the bootloader is misconfigured, or the key is lost, the device may never recover after an OTA failure. After production enablement, JTAG debugging may be restricted by the eFuse. Enable it in stages: do not burn eFuses during development; burn the dev key in pre-production; burn the prod key with write protection in production; keep offline key backups and signed build scripts at every stage.
```

Fifth: "NVS size + OTA resumption + SPIFFS":

```
nvs 0x6000 (24KB) may be insufficient when simultaneously storing WiFi credentials, OTA retry state, resumption offsets, and rollback counters. ota_resumption may write NVS frequently, increasing wear. SPIFFS is no longer recommended; LittleFS is preferred. 8MB PSRAM does not solve the OTA buffering problem.
```

Maybe not "severe" but include.

Could instead include "missing certificate pinning / server certificate rotation" as the fifth. Hmm. Which is more severe? NVS size is not severe; cert rotation is more likely. But the user's top risks already mention eFuse, etc. We'll maybe combine the fifth as "two medium risks: partitions/resources and certificate rotation," or choose 5: "OTA URL / certificate pinning and server operations lack rotation." Let's decide.

The request says "3-5 most severe defects/risks." We can include 5: rollback, app verification, factory fallback, Secure Boot lifecycle, resource/NVS. The certificate rotation can go in the omitted points. That's fine.

Now answer question 1 with details.

Potential extra: "ArduinoOTA vs esp_https_ota switch." We need to mention: "ArduinoOTA does not support HTTPS/signatures; if Phase 1 uses ArduinoOTA, it may not use IDF's rollback API; need to check Update.end."

Let's phrase:

```
The boundary is not the OTA client itself, but:
1) Partition table CSV: both must use the same custom partition table. The Arduino default partition usually has no factory + dual OTA + SPIFFS; a layout change requires one full serial erase-and-flash.
2) Bootloader configuration: ESP-IDF rollback/security components live in the bootloader. The Arduino precompiled bootloader may not have rollback enabled; Phase 2 needs a different bootloader.
3) Security/signing: ArduinoOTA is a plaintext self-signed OTA, limited to an isolated LAN; Phase 2 uses HTTPS + signing.
```

Need maybe: "if Phase 1 uses PlatformIO + Arduino, configure `board_build.partitions = custom_16MB.csv` and `board_upload.flash_size = 16MB`; if using the Arduino IDE, select the custom partition scheme in the Tools menu."

Question 2:

```
Secure Boot V2 itself does not force-disable UART/JTAG, unless you additionally burn eFuses such as JTAG_DISABLE. So the best minimization strategy is: never burn production eFuses on development devices; keep Secure Boot off during development or use a dev key; serial logs work as usual. In early production, burn the dev key on dedicated "security test" units to validate OTA/rollback while keeping JTAG; in final mass production, burn the prod key and burn JTAG_DISABLE (as needed). Note that once Secure Boot is enabled, every OTA firmware must be signed, or the bootloader rejects it. Flash Encryption is a separate item; if enabled, it further restricts JTAG/flash reading and makes debugging more complex.
```

Question 3:

```
Not worth it. partial_http_download is for very large firmware or extremely unstable networks. This device's firmware normally fits in a 4MB slot, and esp_https_ota's default internal RAM buffer is enough. PSRAM is not suitable as the OTA flash write buffer (the cache may be disabled during flash writes). If enabled, use 4-8KB of internal RAM, not a large PSRAM buffer. Prefer ota_resumption.
```

Need maybe: "if you expect the firmware to approach 4MB, you can enable partial_http_download with an 8KB internal buffer to improve reliability."

Question 4:

```
Base it on the local critical path:
Must pass: RTOS startup, LVGL initialization and rendering a local test page, backlight, touch I2C ACK, WiFi STA connects and obtains an IP, OTA task alive.
Degradable: WebSocket server connection / receiving messages. An unreachable server must not cause a rollback, otherwise a cloud outage would mark good firmware as bad. Design a "minimum local UI" that shows device status; once it renders successfully, display/touch are proven usable.
Flow: run stably for 30-60s after boot with no reset; any hardware/initialization failure triggers esp_ota_mark_app_invalid_rollback_and_reboot; remote service failures are only logged, not failed.
```

Question 5:

```
Yes, with conditions. As a transition before Secure Boot, at minimum:
- Sign the manifest (RSA/ECDSA, public key embedded)
- Verify the firmware sha256 before writing to the OTA partition
- Version is monotonically increasing / downgrades forbidden, min_version
- Replay protection: the manifest carries issued_at/nonce, with freshness checking
- HTTPS pinned CA
But note: application-layer verification cannot prevent flashing custom firmware via UART/JTAG, bypassing OTA; it protects the OTA channel. If you use esp_https_ota directly, writing as it downloads, sha256 verification is awkward; you may need to download to a PSRAM/SPIFFS staging area first, then esp_ota_write after verification. Another compromise is to read back and verify sha256 after download but before reboot, though the image is already in the OTA slot; on failure you must mark the target partition bad or re-download. Recommended: wrap a custom OTA: http download → PSRAM/storage temp file → manifest signature verification + SHA256 → `esp_ota_write`.
```

Now "final conclusion: is the scheme feasible? What changes are needed?" We'll state: feasible but conditional; v0.1 cannot go directly to production. Modifications needed as listed. Maybe a table.

Need "supplement any omitted key points (such as partition table, rollback timing, security, power, etc.)" We'll provide a bullet list including:

- Partition table / storage layout: use LittleFS, maybe a separate `nvs_ota` partition, ensure alignment and max app size. Provide a suggested revised partition table, maybe:

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

But note offsets: phy_init at 0x13000 then the next app at 0x20000. The gap from 0x14000 to 0x20000 is okay. But maybe phy_init data needs 0x1000 at 0x11000? It's fine. Check: otadata at 0x11000 size 0x2000 ends at 0x13000; phy_init at 0x13000; ends at 0x14000; app at 0x20000. Gap 0xC000. okay.

If using Secure Boot v2, the partition table offset must be 0x8000? yes.

Need to mention: "factory reset must erase/write otadata? Actually `esp_ota_set_boot_partition(factory)` writes otadata to point to factory. A 'factory reset' may also erase NVS credentials. Decide the behavior."

- OTA resumption details: does `esp_https_ota` require `CONFIG_OTA_ALLOW_HTTP`? No.

- Server certificate:

```
cert_pem should contain the CA certificate, not the leaf certificate; support certificate rotation: either deliver a new CA public key via the manifest (but the manifest itself must be signed) or embed two root certificates at flash time.
```

- Power: brownout, supply stability during flash write; if battery, do OTA only if sufficient charge; disable modem sleep during download to avoid connection drop; use `esp_wifi_set_ps(WIFI_PS_NONE)` during OTA then restore.

- Flash wear/resume: don't write NVS every chunk; use periodic offset saves or only on interruption.

- Logging/diagnostics: save the crash reason, boot count, OTA state to NVS/SPIFFS to diagnose rollback.

Need maybe mention: "factory partition and Secure Boot: factory must be signed if Secure Boot is used; factory can be built as a minimal OTA-only firmware that connects and reflashes. This is a good production strategy."

Could include: "recommend adding an `ota_status` NVS namespace to store the last attempt result for telemetry."

Let's now write the final answer.

Need to maintain technical accuracy. Use the terms:

- `esp_ota_mark_app_valid_cancel_rollback`
- `esp_ota_mark_app_invalid_rollback_and_reboot`
- `esp_ota_set_boot_partition`
- `esp_ota_get_state_partition`
- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`
- `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT`

Need maybe mention "PENDING_VERIFY state and bootloader behavior" accurately. Let's verify whether `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` exists? I think yes, but maybe not.
