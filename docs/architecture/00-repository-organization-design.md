> Chinese version: [00-repository-organization-design.zh-CN.md](./00-repository-organization-design.zh-CN.md)

# Agent Widget: Repository Organization and Base Architecture Design

> Date: 2026-08-23
> Status: Confirmed; waiting to reorganize the repository according to this design

## Goal

`agent-widget` is the single official GitHub repository. It will build ESP32-S3 firmware and host verifiable OTA releases through GitHub Releases.

The repository also holds reproducible designs, protocols, and verification evidence; it does not store temporary PoCs, build artifacts, private keys, dependency caches, or device-specific data.

## Scope and Boundaries

| Content | Handling | Reason |
|---|---|---|
| Waveshare 3.5B hardware, development environment, and LVGL research documents | Include under `docs/hardware/` and `docs/research/` | Stable reference for later development |
| OTA design, Wokwi serial evidence, and retrospectives | Include under `docs/ota/` | Preserve verified conclusions and limitations |
| `esp32-wokwi-ota` `.ino` files, Python build scripts, and `.bin` files | Do not migrate | Standalone Arduino/ESP32 PoC, not the target S3 firmware |
| `esp32-lvgl-sim` upstream clone, submodules, and build directories | Do not migrate | Large in size and an external LVGL reference project |
| Screenshots | Keep only curated images that illustrate the UI design, under `docs/ui/assets/` | Easier review without bloating the repository |
| Keys, certificates, device logs, firmware, and SDK/dependency caches | Keep local and ignore via `.gitignore` | Security, reproducibility, and repository size |

## Target Directory Layout

```text
agent-widget/
├── firmware/                  # Future single ESP-IDF ESP32-S3 firmware
├── macos-client/              # Optional macOS collector/forwarder; design and experiment notes first
├── protocols/                 # Cross-process/cross-network message contracts and transport experiments
├── simulator/                 # Future reproducible PC LVGL simulator
├── experiments/               # Trackable experiment notes; local artifacts ignored by default
├── docs/
│   ├── architecture/          # This design and ADRs
│   ├── hardware/              # Board and toolchain material
│   ├── ui/                    # Information architecture, interaction, performance acceptance, screenshots
│   ├── transport/             # Data path from Mac/Agent/server to the device
│   ├── ota/                   # OTA design, verification evidence, release process
│   └── research/              # Raw research and summaries of external material
├── .gitignore
└── README.md
```

Directories may be empty; before entering the corresponding implementation phase, put a README or design document there first, to avoid creating scaffold code with no purpose.

## Three Product Directions

### 1. Agent Status Collection and Transport

The device consumes only the unified `AgentStatus` contract and knows nothing about the log formats of Codex CLI, Claude Code, or Copilot CLI.

```text
Agent or macOS adapter -> AgentStatus -> transport -> ESP32 device
```

The first-priority verification path is: an agent or its automation script calls an HTTP API, a server publishes over MQTT, and the ESP32 subscribes to MQTT.

The macOS client is an optional adapter: implement it only when directly collecting local CLI status is significantly more reliable or convenient. BLE and local-area Wi-Fi are comparison experiments and must not block the MQTT mainline. All paths must produce exactly the same `AgentStatus` data.

### 2. ESP32 UI and Performance

Terminology is fixed as follows:

- **Panel**: one full screen of the horizontally sliding pages.
- **AgentCard**: the status card inside a Panel that shows one agent.
- **SettingsPanel**: the always-present settings Panel, not mixed into AgentPanel.
- **PanelIndicator**: the clickable position dots at the bottom of the screen; color/shape also express the aggregated status of the corresponding Panel.

Each **AgentPanel** combines 1--2 `AgentCard`s. The interface supports English and Chinese from day one; the protocol carries stable status codes and message keys, and the device maps copy to the current language — English display copy must never be treated as protocol status.

Performance acceptance is based on real devices: 16-bit color depth, PSRAM buffers, partial-invalidation redraws, reused widgets, and a small number of short animations. The PC simulator only validates layout, swipe rules, and status mapping; it does not replace on-device frame-rate, touch-latency, or memory verification.

### 3. OTA Infrastructure

The first USB flash installs only the bootstrap firmware; all subsequent routine upgrades must go through OTA:

```text
GitHub Actions build -> Release + signed manifest -> HTTPS OTA
-> inactive OTA slot -> reboot -> health check -> valid / rollback
```

The production implementation uses ESP-IDF, dual OTA app partitions, and rollback. The health check must at least cover display initialization, Wi-Fi connectivity, the status-transport task being alive, and the UI main loop being alive. Secure Boot and Flash Encryption get a separate plan for key management and irreversible eFuse enablement only after this pipeline has completed multiple real-device success/failure rollback drills.

## Git Management Principles

Commit: source code, partition tables, build configuration, tests, message schemas, documentation, a small number of curated screenshots, and human-confirmed serial evidence.

Keep local / ignore: `build/`, `.pio/`, `.idf/`, `managed_components/`, `*.bin`, `*.elf`, `*.map`, local `sdkconfig` overrides, keys/certificates, download caches, temporary logs, videos, and experiment outputs. Release firmware never enters Git history; CI uploads it to a GitHub Release.

## Non-Goals

- Do not dress up the existing Arduino/Wokwi PoCs as production ESP32-S3 code.
- Do not vendor the 880 MB LVGL upstream clone or submodule into this repository.
- Do not commit to completing MQTT, BLE, local-area Wi-Fi, and the macOS client all at once; they are alternative paths eliminated by evidence.
- Do not burn Secure Boot eFuses early in development.
