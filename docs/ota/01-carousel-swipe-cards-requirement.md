> Chinese version: [01-carousel-swipe-cards-requirement.zh-CN.md](./01-carousel-swipe-cards-requirement.zh-CN.md)

# 01-Carousel Swipe Cards Requirement (Horizontal Swipe + Loop + Bottom Indicator)

> Date: 2026-08-22
> Project: ESP32-S3-Touch-LCD-3.5B (320×480 portrait, LVGL 9.6, validated in simulator)
> Status: Requirements finalized, pending implementation

---

## 1. Functional Requirements

### 1.1 Swipe Cards (Carousel)
- Cards are arranged horizontally, **the card count is dynamic** (N cards, N ≥ 1)
- Swipe left/right with a finger to switch cards
- Swiping has a **snap effect** (on release, auto-align to the nearest card, never resting between cards)

### 1.2 Infinite Loop (Seamless Carousel)
- **Keep swiping left past the first card → go to the last card** (loop)
- **Keep swiping right past the last card → go to the first card** (loop)
- Visually seamless; the user perceives the cards as a ring with no ends

### 1.3 Page Dots (Bottom Indicator)
- N dots at the bottom, showing the current card's position among all cards
- The dot for the current card is **highlighted** (different color/size); the rest are dimmed
- Updates **in real time** as the user swipes

### 1.4 Card Content (tied to the Agent Status project)
Each card shows one Agent's status (matching the agent-telemetry project data):
```
Agent name (Codex / Claude Code / Copilot)
Status (RUNNING / WAITING / SUCCESS / ERROR)
Task description
Token usage / time
```

---

## 2. Technical Constraints and Smoothness Requirements (Critical)

1. **LVGL 9.6 has no built-in carousel component** → implement on top of native scroll + snap (no extra libraries)
2. **Loop implementation**: mirrored copies at both ends (a copy of the last card inserted before the first, a copy of the first card appended after the last) → when the swipe reaches a copy, jump back to the real card without animation
3. **Smoothness is the top priority**:
   - Single vs. double buffering: double buffer in the PC simulator; on real hardware use `LV_COLOR_DEPTH=16` + PSRAM dual buffer
   - Card content should **avoid** gradients/shadows/semi-transparency and other expensive re-render effects (they are smoothness killers under the SW renderer)
   - Prefer text, rounded rectangles, and solid color blocks
   - Moderate animation times (200-300ms); follow the finger using scroll's native drag behavior (no extra per-finger animation)
   - If frames are occasionally dropped, keep gesture responsiveness (dropped frames are acceptable; jank is not)
4. **320×480 portrait layout**:
   - Card area: top ~400px (full width; each card is one screen wide)
   - Indicator area: bottom ~60px, centered
5. **Dynamic card count**: support rebuilding/adding/removing cards when the data source changes (reserve a `rebuild_cards()` interface)

---

## 3. Acceptance Criteria (Simulator)

- [ ] Multiple cards (≥5) snap correctly when swiped left/right
- [ ] Swiping left on the first card → goes directly to the last card (loop)
- [ ] Swiping right on the last card → goes directly to the first card (loop)
- [ ] Bottom dots highlight correctly as the user swipes
- [ ] Long lists stay smooth (visually fluid in the simulator)
- [ ] Clean code structure (card data separated from the UI, ready to consume agent-telemetry data later)

---

## 4. Sample Data (Card Content)

```c
// Card data (simulating the agent-telemetry session model)
card_t cards[] = {
    {"CODEX",    "RUNNING", "Refactoring auth middleware", 12482, 134},
    {"CLAUDE",   "WAITING", "Waiting for permission",      4300,  12},
    {"COPILOT",  "SUCCESS", "OTA design research",         20414, 356},
    {"CODE",     "ERROR",   "Build failed: link error",     812,   5},
    {"HERMES",   "IDLE",    "No active task",               0,     0},
};
```

---

## 5. Landing Location

- Implementation: `/mnt/sdc1/Playground/esp32-lvgl-sim/src/main.c` (simulator demo)
- Documentation: this directory (local design notes)
