> Chinese version: [06-ota-simulation-options.zh-CN.md](./06-ota-simulation-options.zh-CN.md)

# 06-ESP32 Full-Machine Simulation Options Research (can the complete OTA flow run on a PC)

> Date: 2026-08-22
> Question: besides the LVGL UI simulator (esp32-lvgl-sim already built), is there a full-machine simulation that can run OTA end to end (download → write flash → reboot → verify → rollback)?
> Conclusion: ✅ **Yes, three paths** (Wokwi / QEMU / ESP-IDF Linux target), each with trade-offs

---

## 1. Conclusion at a Glance

| Solution | How it runs | WiFi simulation | OTA runnable? | UI | Best for |
|---|---|---|---|---|---|
| **Wokwi** ⭐ | Browser | ✅ Full virtual AP (Wokwi-GUEST) + real network stack + PCAP capture | ✅ Existing OTA example projects | ✅ Virtual LCD can display | Fastest verification in the Arduino ecosystem |
| **QEMU (espressif fork)** ⭐ | Local | ✅ WiFi NIC simulation (esp32_wifi) + qemu_internet component | ✅ Flash persistence + real bootloader execution | ✅ Virtual framebuffer (esp_lcd_qemu_rgb) | ESP-IDF projects + rigorous rollback/Secure Boot testing |
| **ESP-IDF Linux target** | Local build | ⚠️ Component level (esp_wifi host implementation, limited) | ⚠️ Partial component support; OTA not complete | ❌ | Unit tests / CI |
| **Velxio** (new, official) | Browser | ✅ | To be verified | ✅ | New option, watch and wait |

## 2. Solution Details

### 2.1 Wokwi (easiest, recommended first for validating OTA logic)

- **Address**: https://wokwi.com — works in the browser, no installation
- **WiFi simulation**: virtual AP `Wokwi-GUEST` (no password, channel 6), complete 802.11 → IP → TCP/UDP → DNS/HTTP/MQTT network stack, **PCAP can be downloaded and analyzed with Wireshark**
- **OTA support**: official example [OTA](https://wokwi.com/projects/389801812438455297) + [WiFi ota test](https://wokwi.com/projects/387266104488294401) — flash is writable and persists across reboots, so you can verify "download → write flash → reboot → new firmware runs"
- **Arduino compatible**: directly runs firmware compiled with the Arduino core (our PlatformIO/Arduino projects are portable)
- **Limitations**: the free Public Gateway goes through the cloud (traffic is monitored); a private gateway (connected to local localhost) is paid; no real peripheral timing (I2C/SPI touch simulation is limited)

### 2.2 QEMU (espressif fork, most rigorous, suitable for rollback/Secure Boot verification)

- **Install**: `python $IDF_PATH/tools/idf_tools.py install qemu-xtensa` + system dependencies (libgcrypt20/libglib2.0-0/libpixman-1-0/libslirp0)
- **Launch**: `idf.py qemu monitor` (build + simulate + serial monitor) | `idf.py qemu --gdb monitor` (GDB debugging)
- **Simulation capabilities**:
  - CPU/memory/peripherals + **flash persistence** (qemu_flash.bin: bootloader + partition table + app placed by offset)
  - **eFuse simulation** (`idf.py qemu efuse-burn ...`) → **Secure Boot / Flash Encryption can be tested without risk** (burning eFuses on real hardware is irreversible; with QEMU you can try anything)
  - **WiFi/BLE NIC simulation** (esp32_wifi) + network access (qemu_internet component for HTTP downloads)
  - **Virtual framebuffer** (`--graphics` + esp_lcd_qemu_rgb component) → LVGL UI can be displayed
- **Value for OTA verification**: dual-partition switching, bootloader rollback logic, the PENDING_VERIFY state machine, Secure Boot signature verification — **all executed for real**, consistent with real-device behavior
- **Limitations**: aimed at ESP-IDF projects (our Arduino projects need porting or an idf.py build); no real touch/peripheral timing

### 2.3 ESP-IDF Linux target (host build)

- Docs: "Running ESP-IDF Applications on Host"
- Components are implemented on Linux (esp_wifi has a host simulation), usable for CI unit tests
- **Currently only limited component support; the OTA chain is not complete** — not suitable for running the full flow

### 2.4 Velxio (new release by Espressif, 2026-07)

- Browser-based QEMU core simulation, runs real firmware + WiFi/MQTT demo
- New project, maturity to be observed; listed as an alternative for now

## 3. Recommended Path for Us (combined with the existing environment)

```
Development stage 1 (UI iteration):  LVGL PC simulator (esp32-lvgl-sim already built) ✅
Development stage 2 (OTA logic):     Wokwi (Arduino project + existing OTA example, fastest way to run "download → reboot → new version")
Development stage 3 (rigorous validation): QEMU + ESP-IDF (dual-partition rollback / Secure Boot / eFuse simulation)
                                     — fully corresponds to the esp_https_ota path selected in 05
Real-device stage:                   ESP32-S3-Touch-LCD-3.5B (final acceptance)
```

## 4. Key Reminders

1. **Wokwi verifies "application logic"** (HTTP download + Update class writes flash + reboot); the bootloader rollback state machine depends on the Arduino core's rollback support — you need to confirm whether the Wokwi ESP32-S3 model's partition table includes otadata
2. **QEMU verifies "system behavior"** (bootloader + otadata + rollback), the closest simulation of OTA to the real device; eFuse simulation makes Secure Boot testing risk-free
3. The two complement each other: **Wokwi is fast, QEMU is accurate**
4. OTA server: a local HTTPS static service is enough (development phase); Wokwi uses the Public Gateway to reach the public GitHub Releases (corresponding to the SafeGithubOTA solution) or a private gateway to reach the local machine

---

## References

- [ESP-IDF QEMU Emulator (ESP32-S3) official docs](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/tools/qemu.html)
- [Wokwi ESP32 WiFi simulation docs](https://docs.wokwi.com/guides/esp32-wifi)
- [Wokwi OTA example project](https://wokwi.com/projects/389801812438455297)
- [Wokwi WiFi OTA test](https://wokwi.com/projects/387266104488294401)
- [Ebiroll/qemu_esp32 (WiFi NIC simulation)](https://github.com/Ebiroll/qemu_esp32)
- [Production ESP32: Internet Access in QEMU](https://productionesp32.com/posts/internet-in-qemu/)
- [ESP-IDF Running Apps on Host](https://esp32.ai/idf/esp32/api-guides/host-apps)
- [Velxio: Browser-based ESP32 simulation (official blog)](https://developer.espressif.com/blog/2026/07/velxio-browser-based-esp32-simulation/)
