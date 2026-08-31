---
title: "Panel UI Design: Carousel + Vertically Scrolling Details + Status Indicator"
date: 2026-08-24
status: proposed
tags:
  - ui
  - panel
  - carousel
  - agent-status
  - ota
  - design
description: "Panel carousel UI design for the ESP32-S3-Touch-LCD-3.5B (320x480 portrait / LVGL): one Panel per agent, vertically scrolling details, status-colored indicator, and the complete interaction and state machine for the OTA / firmware-update UI."
---
> Chinese version: [panel-ui-design.zh-CN.md](./panel-ui-design.zh-CN.md)


# Panel UI Design: Carousel + Vertically Scrolling Details + Status Indicator

> Corresponding task: `AW-005` (Specify Panel UI and establish real-device responsiveness measurements)
> Visual sources: four directions generated with ChatGPT (A dark information dashboard / B minimalist glanceable / C lightweight cards / D data-and-operations view) — **reference only, not the final design**. This design reworks those directions as raw material.
> Hardware facts: `docs/hardware/board-spec-constraints.md` (authoritative); terminology follows `docs/architecture/00-repository-organization-design.md`.
> OTA facts: `docs/ota/02-ota-design-esp-https-rollback.md`, `docs/ota/04-ota-evaluation-conclusion.md`.

---

## 0. Design Positioning

- Device: Waveshare ESP32-S3-Touch-LCD-3.5B, **320×480 portrait** (native ROT 0), RGB565 (16bpp), AXS15231B (QSPI display + I2C 0x3B touch), 8MB PSRAM, 16MB Flash.
- GUI framework: **LVGL**. The version is locked in AW-005 (official demo v8.4 / v9.2.2; this repo's PC simulator is v9.x — pick one; mixing APIs is forbidden).
- Visual base: **Option A (dark information dashboard)** — high information density, strong hierarchy, dark and low-distraction, the best fit for agent information of "status word + progress/usage". Option C (cards) and Option B (minimalist) serve as references for interaction and whitespace; Option D (data operations) informs only the trade-offs for the detail-page charts.
- Fixed terminology:
  - **Panel**: one full screen page that slides horizontally.
  - **AgentPanel**: a Panel that shows one agent session's status.
  - **UpdatePanel**: the resident system Panel for OTA / firmware updates (P1).
  - **SettingsPanel**: the permanently present settings Panel (always the last one).
  - **AgentCard**: the status card inside a Panel that shows one agent.
  - **PanelIndicator**: the clickable position dots at the bottom of the screen; their color/shape simultaneously express the aggregated status of the corresponding Panel.

---

## 1. Panel Set and Circular Carousel

### 1.1 Structure

```text
[AgentPanel₁ … AgentPanelₙ] → [UpdatePanel] → [SettingsPanel]
```

- **Horizontal carousel**: one Panel per screen, swipe left/right, **infinite loop** (mirrored copies at the head and tail make the wrap seamless and jump-free).
- **Dynamic set**: `n` = the current number of active agent sessions (may be 0).
  - `AgentPanel₁ … AgentPanelₙ`: dynamically generated, one per agent session.
  - `UpdatePanel`: a **resident** system Panel (OTA is P1; every device must be able to test updates). Always present, after the agent Panels and before Settings.
  - `SettingsPanel`: **fixed as the last one**, always present.
- Empty state: with no active agents the set is `[UpdatePanel, SettingsPanel]`, and an empty-state page is shown (see §9).
- **Snap on release**: finger dragging uses native scroll behavior that tracks the finger, with no extra tracking animations; on release, the nearest Panel aligns automatically.

> Alternative (not adopted; switchable): OTA does not get its own panel; it lives only as a "system update area + full-screen overlay" at the top of the SettingsPanel. This design adopts a dedicated `UpdatePanel` because OTA status is the easiest to see at a glance during development, and it stays consistent with the "scroll vertically within each Panel to expand details" interaction model.

### 1.2 Data-Driven

- Sessions added/removed → `rebuild_panels()`: rebuild the carousel panels + the number of indicator dots, preserving snapping and looping.
- Dynamic card count: reserve a rebuild interface; additions/removals do not rebuild the whole screen, only the affected Panels are added/removed.
- Each AgentPanel combines **1–2 AgentCards** (per the architecture document); this design defaults to **one Panel per agent**, so one Panel holds one AgentCard, and the expanded state carries more of that agent's information (see §2).

---

## 2. Information Layering Within a Panel (Design Core)

An AgentPanel has **collapsed / expanded** two levels, switched by **vertical scrolling**:

| Level | Content | How to reach |
|---|---|---|
| **Collapsed (default)** | agent name · status color + icon · current task in one line · key metrics (token progress bar / %) | visible on entry |
| **Expanded** | activity timeline, token usage breakdown (input/output), elapsed time, context %, cost, mini trend / small bars | swipe up |

- **The collapsed state fits on one screen; no scrolling.**
- **The expanded state is a scrolling container**: it only loads "more" blocks; when content does not fill a screen, disable scrolling to avoid blank space.
- **Default rule**: entering / returning to a Panel **resets to the collapsed state** (deterministic, predictable); only a tap on expand enters the expanded state. Every Panel (including Update and Settings) follows this default.

The same rule applies to `UpdatePanel` and `SettingsPanel`: core status by default, scroll vertically for more.

---

## 3. Resolving Gesture Conflicts (Critical)

The horizontal carousel and vertical scrolling share the same screen; **direction locking** resolves the conflict:

| Gesture | Action | LVGL implementation |
|---|---|---|
| Horizontal swipe | Switch Panel (outer carousel, HOR lock) | outer horizontal scroll container |
| Vertical swipe | Expand/collapse the details inside the Panel (inner scroll, VER lock) | inner vertical scroll container |
| Tap an indicator dot | Jump to the corresponding Panel | dot tap event |
| Tap a card element | (optional) expand details / run an action | card event callback |

- Use `LV_OBJ_FLAG_SCROLL_ONE` / `scroll_dir` so the outer layer only accepts horizontal swipes and the inner layer only vertical ones, preventing accidental triggers.
- Touch: AXS15231B integrated touch (I2C 0x3B, up to 2 points, ROT 0 maps directly to 320×480, no swap/mirror).

---

## 4. PanelIndicator (Bottom Indicator) — Dual Semantics

- **N dots = the positions of N Panels.**
- **Dot color = the aggregated status of that Panel's agent** (or the system status of Update/Settings).
- The current Panel's dot: **enlarged + outlined/highlighted**; the rest are small, dim dots.
- Dots themselves differ by status color (**no text**); one glance tells you whether each agent/system is busy, waiting, failing, or done.
- In the empty state only the system dots remain (Update + Settings).
- Reserve a bottom safety margin for the indicator area so touch hits don't interfere with the content area.

---

## 5. Status → Color / Icon / Copy Mapping

> Status codes come from the `AgentStatus` contract. The UI shows **status color + icon + bilingual copy keys**, not wall-to-wall English. This table also drives the indicator colors, the card status badges, the detail-page banner, and the update status.

### 5.1 Agent Status

> The "⏸ ▶ 🧠 ✓ ✕ ○" glyphs are illustrative; the device uses **theme-built-in drawn shapes/vector icons** (or symbol glyphs embedded in the font) and **never renders emoji**. Each status has one fixed icon semantic that switches together with its status color.

| AgentStatus | Indicator/badge color | Icon semantic | Chinese copy | English key |
|---|---|---|---|---|
| `WAITING` | Amber `0xFFB300` | pause/wait | 等待 | waiting |
| `RUNNING` | Green `0x00C853` | play/in progress | 运行中 | running |
| `THINKING` | Blue `0x2094F3` | brain/thinking | 思考中 | thinking |
| `DONE` | Teal `0x00BFA5` | check/done | 完成 | done |
| `ERROR` | Red `0xFF3D00` | cross/error | 出错 | error |
| `IDLE` / `OFFLINE` | Gray `0x7A7A7A` | dot/outline | 空闲 · 离线 | idle / offline |

- Logical mapping: `NEEDS_INPUT → WAITING`; `SUCCESS → DONE`; `IDLE`/`OFFLINE` stay separate.
- **Aggregated status** = the highest-priority exception/active state among the active ones: `ERROR > RUNNING > WAITING > DONE > IDLE`.

### 5.2 Update (OTA) Status

| Stage | Color | Copy (Chinese / English key) |
|---|---|---|
| Update available | Blue `0x2094F3` | 有新版本 / update_available |
| Updating (downloading/verifying) | Amber `0xFFB300` | 更新中 / updating |
| Up to date | Gray `0x7A7A7A` | 已是最新 / up_to_date |
| Rolled back | Red `0xFF3D00` | 已回滚 / rolled_back |

---

## 6. OTA and Firmware Update UI (P1 · Highest Priority)

> Positioning: this UI is **not just for the user to see status — it is a test instrument for verifying that OTA works during development**. Corresponding to the AW-006 pipeline's three phases (check / download / self-test and rollback), the UI must be observable, controllable, and diagnosable at every phase.

The OTA/update UI consists of **three surfaces**.

### 6.1 Full-Screen Update Overlay — State Machine Taking Over the Screen

While an update is in progress it displays unconditionally in full screen so no agent content covers it. The state machine aligns strictly with the OTA pipeline:

| Stage | Screen presentation | User intervention |
|---|---|---|
| Checking for updates | spinner + "正在检查更新…" (Checking for updates…) | Cancelable |
| New version available | old/new version numbers + size + changelog + "下载并安装" (Download and install) | Confirm / dismiss |
| Downloading | **progress bar + bytes downloaded + speed** (driven by `ESP_HTTPS_OTA` events) | Not interruptible (prevents partial writes) |
| Verifying | spinner + SHA256/signature verification | — |
| About to reboot | "更新完成，正在重启…" (Update complete, rebooting…) | — |
| Self-test (PENDING_VERIFY) | the new firmware renders the **self-test page** on its first screen (see 6.2) | — |
| Success | green ✓ "更新成功 · 运行 vX" (Update succeeded · running vX) | — |
| Failure / rollback | red ✕ "更新失败，已回滚到 vPrev" (Update failed, rolled back to vPrev) + reason | View diagnostics |

### 6.2 Self-Test / Health Screen — the Rollback-Decision Screen (the Most Critical for "Can OTA Work at All?")

Per OTA-04 Q4: after the new firmware boots it enters `PENDING_VERIFY`; **this self-test page must render first** to prove that display + touch initialization succeeded, and the page itself is the decision surface for whether to `mark_valid` or roll back. Items are checked off or crossed out one by one:

- [x] Display initialization (this page rendering already proves it)
- [x] Touch I2C ACK
- [x] Wi-Fi STA connected and IP obtained
- [x] OTA check task alive
- [ ] Server reachable (**recorded only, no rollback** — a cloud-side fault must not mark good firmware as bad)

All pass → `esp_ota_mark_app_valid_cancel_rollback()`; any **required item** fails/times out → show "自检失败，回滚中" (Self-test failed, rolling back) and trigger `esp_ota_mark_app_invalid_rollback_and_reboot()`.

> **This page is the visual criterion for the AW-006 rollback drill.** The rollback window is configurable via `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` (default 5s; recommended to raise it to 30–60s).

### 6.3 System Update Area (the UpdatePanel Body)

As the resident system Panel (P1), it provides observable diagnostics during the testing phase:

- **Current version** + **running slot** (factory / ota_0 / ota_1) + build info.
- **"Check for updates" button** + time of last check + result.
- **Diagnostics**: boot count / last crash reason / OTA status / rollback history (from NVS, for rollback cause analysis).
- While downloading, progress also appears here (in sync with the 6.1 full-screen overlay).

### 6.4 OTA Pipeline → UI Mapping

```text
Check for updates → HTTPS fetch of manifest (signature verification + freshness check)
  → version > current? → download to staging area → verify sha256+signature → esp_ota_write to the free slot
  → reboot (bootloader sets PENDING_VERIFY)
  → self-test (6.2: display/touch/Wi-Fi/OTA task)
  → all pass → mark_valid | fail/timeout → mark_invalid_rollback
  → N consecutive failures / GPIO long-press → boot the factory recovery firmware
```

---

## 7. Data Flow (AgentStatus → UI)

- The device consumes only the unified `AgentStatus`.
  - **Status code** → color/icon (§5).
  - **Values** → progress/statistics.
  - **Copy** → mapped from message keys by the current language (the protocol carries no display English).
- Rendering uses **incremental updates**: only the affected regions are redrawn when the status code/value changes (card header / progress bar / detail block), never full-screen; partial invalidation redraw.
- Sessions added/removed → `rebuild_panels()` (§1.2).
- Data and UI are decoupled: acquisition/transport run in tasks, the UI runs in the `lv_timer_handler()` main loop; data first enters a buffer and the UI only reads the buffer to render.

---

## 8. Bilingual Support and Fonts

- The UI supports **Chinese and English** from day one.
- The protocol carries stable status codes and copy keys; the device maps copy by current language. **Display English must never be used as protocol status.**
- The device **embeds a Chinese font** (converted with LVGL's font tools, subsetting to embed only the characters needed to save Flash); the PC simulator's host fonts are only for layout reference.
- The language switch lives in the SettingsPanel.

---

## 9. Settings Panel and Empty / Error States

### 9.1 SettingsPanel (Fixed at the End)

- Language switching (Chinese / English).
- Theme / brightness.
- About (firmware version, device ID, running slot).
- (OTA-related items are concentrated in the UpdatePanel, not duplicated in Settings; here only the "About/version" read-only display.)

> Early on (during OTA testing), Settings may also show a read-only summary of the "system update area," but the split of responsibilities with the UpdatePanel must stay explicit to avoid the two places disagreeing.

### 9.2 Empty / Error States

- No active agents: empty-state page + system dots only (Update + Settings).
- Offline / transport interrupted: the status card shows `OFFLINE` in gray, the matching indicator dot turns gray, no full-screen error.
- `ERROR`: the status card + indicator dot turn red, the body shows the reason; scroll for details.

---

## 10. Performance and Implementation Constraints (Real-Device Acceptance, No Conclusions from sim Alone)

- 16-bit RGB565, full-screen PSRAM draw buffer, partial-invalidation redraws, widget reuse, short animations (200–300ms).
- **Avoid gradients/shadows/semi-transparency** — they kill smoothness under the software renderer; stick to solid color blocks, rounded rectangles, and text.
- Prioritize gesture responsiveness (occasional dropped frames are acceptable; jank is not).
- Chinese uses the device-embedded font; store values as integers ×100/×1000 and divide back.
- **The PC simulator verifies only layout, swipe rules, status mapping, and interaction semantics**; frame rate, touch latency, memory/PSRAM, Wi-Fi reconnection, and OTA rollback can only be measured on real hardware (AW-002/003/005).

---

## 11. Acceptance Scope (AW-005)

- [ ] Panel / AgentCard / SettingsPanel / UpdatePanel / PanelIndicator behavior specified (this document).
- [ ] One Panel per agent (extensible to 1–2 cards).
- [ ] Collapse/expand, horizontal circular swiping, direction locking, snapping, and indicator status colors specified.
- [ ] Bilingual (Chinese/English) string keys specified; protocol payloads do not vary with display language.
- [ ] Touch latency, frame rate, and memory baselines measured on real hardware (measured in AW-005, not sim conclusions).
- [ ] The three OTA surfaces (6.1/6.2/6.3) align with the AW-006 pipeline and can serve as rollback-drill criteria.

---

## 12. Open Points / Switchable Decisions

1. **Dedicated OTA panel (adopted) vs. Settings-top-only**: this design uses `…→[UpdatePanel]→[SettingsPanel]` with a resident UpdatePanel. If switched to "Settings-top-only," there is one fewer indicator dot, and update status is visible only inside Settings.
2. **Cross-panel expand/collapse memory**: the default is settled — **entering/returning to any Panel resets to the collapsed state** (deterministic, predictable); the expanded state is not remembered across Panels. If "keep last expanded" is wanted later, append it here.
3. **LVGL version**: v8.4 (official demo, more tutorials) vs v9.x (matches the PC sim) — once locked in AW-005, pin it in this document and `gui-framework.md`.
4. **Whether the update overlay should allow opening "update history/rollback details" from Settings**: this design only provides a read-only summary in the diagnostics area; no full history page is implemented.

---

## References

- `docs/architecture/00-repository-organization-design.md` (Panel/AgentCard/SettingsPanel/PanelIndicator terminology)
- `docs/hardware/board-spec-constraints.md` (authoritative board-level constraints)
- `docs/ui/gui-framework.md` (LVGL version and architecture)
- `docs/ui/data-viz-diagram-design.md` (chart/gauge rendering approach)
- `docs/ota/02-ota-design-esp-https-rollback.md`, `docs/ota/04-ota-evaluation-conclusion.md` (OTA pipeline and self-test/rollback criteria)
- `docs/ota/01-carousel-swipe-cards-requirement.md` (carousel loop/snap/indicator requirements)
