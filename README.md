# agent-widget

**A real-time AI-agent status display built on the ESP32-S3.**

agent-widget turns a Waveshare ESP32-S3-Touch-LCD-3.5B into a live status
dashboard for AI coding agents. It receives reliable status updates, renders
them responsively on a 320×480 capacitive-touch display, and keeps its own
firmware current through a verified OTA release pipeline.

## Goal

The project's end goal is a repeatable, real-device demo:

1. An agent's `AgentStatus` reaches the device over the network (MQTT-first transport).
2. The device renders it responsively on the touch display, one agent per Panel, with status-coded indicators.
3. The device can install verified firmware updates from GitHub Releases — including automatic rollback when a post-update health check fails.

## Status

| Area | State |
|---|---|
| UI design (Panel carousel, expandable agent cards, update overlay) | Specified — see [`docs/ui/panel-ui-design.md`](docs/ui/panel-ui-design.md) |
| OTA release pipeline (GitHub Actions → GitHub Releases → device) | Verified end-to-end (v2.0.0) — see [`docs/ota/`](docs/ota/) |
| Board constraint research (pins, I2C, display, build config) | Authoritative — see [`docs/hardware/board-spec-constraints.md`](docs/hardware/board-spec-constraints.md) |
| MQTT lab (broker + virtual devices + self-verifying demo) | Built and code-reviewed — see [`experiments/mqtt-lab/README.md`](experiments/mqtt-lab/README.md) (21/21 checks) |
| Production firmware (ESP-IDF) | In development |
| AgentStatus contract (MQTT) | Lab draft in `experiments/mqtt-lab/contracts/`; ratification tracked in [#4](https://github.com/agent-widget/agent-widget/issues/4) |


## Project board

Work is tracked as GitHub issues (mirrored from the local `docs.local/tasks.json`):

| Issue | Milestone | Priority |
|---|---|---|
| [#1](https://github.com/agent-widget/agent-widget/issues/1) AW-001 Consolidate repository knowledge and operating contract | M1 | p2 |
| [#2](https://github.com/agent-widget/agent-widget/issues/2) AW-002 ESP-IDF example on real hardware | M1 | p1 |
| [#3](https://github.com/agent-widget/agent-widget/issues/3) AW-003 Minimal ESP-IDF device health baseline | M1 | p1 |
| [#4](https://github.com/agent-widget/agent-widget/issues/4) AW-004 AgentStatus v1 over MQTT (contract + real-device delivery) | M2 | p0 |
| [#5](https://github.com/agent-widget/agent-widget/issues/5) AW-005 Panel UI + real-device responsiveness | M3 | p1 |
| [#6](https://github.com/agent-widget/agent-widget/issues/6) AW-006 GitHub Release OTA pipeline + rollback drills | M4 | p0 |
| [#7](https://github.com/agent-widget/agent-widget/issues/7) AW-007 Transport alternatives evaluation | M2 | p2 |

Milestones: **M1** Foundation & hardware baseline · **M2** MQTT transport & AgentStatus contract · **M3** Panel UI & PC simulator · **M4** OTA pipeline & release process
## Preferred hardware

The current hardware target is the **Waveshare ESP32-S3-Touch-LCD-3.5B**
(SKU 31137; SKU 31334 "3.5B-C" ships with a case and camera).

| Component | Specification |
|---|---|
| SoC | ESP32-S3R8 — dual-core Xtensa LX7 @ 240 MHz |
| Memory | 512 KB SRAM + 8 MB Octal PSRAM |
| Flash | 16 MB QIO NOR flash (W25Q128JVSIQ) |
| Display | 3.5" IPS capacitive touch, 320×480 portrait, 262K colors |
| Display / touch controller | AXS15231B (QSPI display + I2C touch @ 0x3B) |
| Wireless | 2.4 GHz Wi-Fi (802.11 b/g/n) + Bluetooth 5 LE |
| Toolchain | ESP-IDF ≥ 5.4 |

Official links:

- [Product page](https://www.waveshare.com/product/esp32-s3-touch-lcd-3.5b.htm)
- [Wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B)
- [Documentation platform](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B)
- [Official demo repository](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.5B)

## Repository layout

```
agent-widget/
├── docs/            # User-facing documentation (American English primary;
│                    # Chinese counterparts use the .zh-CN.md suffix)
├── firmware/        # Production ESP-IDF firmware (in development)
├── ota-sim/         # Arduino PoC used by the release pipeline (historical)
├── protocols/       # AgentStatus schema and transport contracts
└── scripts/         # CI and publishing helpers
```

## Documentation

- [`docs/architecture/00-repository-organization-design.md`](docs/architecture/00-repository-organization-design.md) — architecture and repository design
- [`docs/hardware/board-spec-constraints.md`](docs/hardware/board-spec-constraints.md) — authoritative board spec, pins, and build constraints
- [`docs/ui/panel-ui-design.md`](docs/ui/panel-ui-design.md) — display UI design
- [`docs/ota/`](docs/ota/) — OTA design, verification evidence, and release pipeline

## License

MIT — see [LICENSE](LICENSE).
