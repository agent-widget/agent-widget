# Transport design

The baseline path is Agent or adapter -> HTTP API -> MQTT broker -> ESP32. BLE, local Wi-Fi, direct Agent delivery, and macOS client work are experiments evaluated against this baseline in AW-007.

## Documents

- [Device registration and device UUID](device-registration-and-uuid.md) (+ [中文](device-registration-and-uuid.zh-CN.md)) — immutable identity from the eFuse base MAC, first-boot MQTT registration with a MAC allowlist, and per-device credential issuance for fleets of hundreds of units.
