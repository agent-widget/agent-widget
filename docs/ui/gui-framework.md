---
title: "GUI Framework Selection"
date: 2026-08-21
status: complete
tags:
  - lvgl
  - gui
  - comparison
description: "ESP32 touchscreen GUI options compared: LVGL vs Arduino_GFX vs SquareLine Studio vs others"
---
> Chinese version: [gui-framework.zh-CN.md](./gui-framework.zh-CN.md)


# GUI Framework Selection

> Created: 2026-08-21

---

## Full Options Comparison

| Option | Type | Learning curve | UI complexity | Data charting | Recommended for |
|---|---|---|---|---|---|
| **LVGL** ⭐ | Full GUI framework | Medium | High (rich widgets) | ⭐ Strong (chart/arc/bar) | Dashboards, multi-page UIs, touch interaction |
| **Arduino_GFX** | Low-level drawing library | Low | Low (lines/rectangles/text) | Medium (hand-written) | Simple status screens, numeric display |
| **TFT_eSPI** | Low-level drawing library | Low | Low | Medium (has sprites) | Fast graphics, games |
| **SquareLine Studio** | Visual designer | Low (drag-and-drop) | Very high (WYSIWYG) | Medium (generates LVGL code) | Fast UI creation, team collaboration |
| **GUI Guider** (NXP) | Visual designer | Low | High | Medium | LVGL ecosystem alternative |
| **ESPHome LVGL** | YAML configuration | Low | Medium | Medium | Home Assistant integration |
| **MicroPython + LVGL** | Scripting | Low | High | Strong | Rapid prototyping (slightly lower performance) |

## Recommendation: LVGL First, Arduino_GFX as the Driver Layer

> ⚠️ **2026-08-24 update**: this section reflects the Arduino rapid-prototyping perspective. The production firmware target is **ESP-IDF** (per the project's internal operating policy), and the production driver layer uses the official `espressif/esp_lcd_axs15231b` (QSPI), not Arduino_GFX. The LVGL version is pending lock-in at AW-005 (official demo v8.4/v9.2.2; this repo's PC simulator is v9.x). The conclusions here serve only as Arduino PoC reference.

**Conclusion (Arduino PoC perspective)** — key points of the **LVGL + Arduino_GFX driver-layer** combination:

1. **The official demo uses exactly this combination** — works out of the box, no porting needed
2. **lv_chart is the only chart widget that works out of the box** — line/bar/scatter + touch point picking + dual Y axes; it is the core of data-driven charts
3. **Rich widget ecosystem**: arc (gauges), bar (progress bars), scale (axes), tabview (multi-page), anim (animation)
4. 8MB PSRAM runs rich LVGL UIs without strain

### Why Not the Others

- **Plain Arduino_GFX**: it can draw, but everything must be hand-written (coordinate math, scaling, touch hit-testing all done by you), making charts expensive to build
- **TFT_eSPI**: Type B is QSPI + AXS15231B, and TFT_eSPI does not officially support this driver (only Arduino_GFX does) — **excluded**
- **SquareLine Studio**: the free tier can export LVGL code and is good for scaffolding the UI skeleton, but chart logic still has to be hand-written; the generated code is v8-style, so mind the version match
- **ESPHome LVGL**: good for Home Assistant integration and drawing simple widgets purely in YAML; complex charts are still limited by YAML's expressiveness

## LVGL v8 vs v9 (Important)

| | LVGL v8.4 (official demo) | LVGL v9.x |
|---|---|---|
| Display object | `lv_disp_drv_t` / `lv_disp_drv_register` | `lv_display_t` / `lv_display_create` |
| Screen object | `lv_scr_act()` | `lv_screen_active()` |
| Buffers | `lv_disp_draw_buf_init` | `lv_display_set_buffers` |
| Charts | `lv_chart_*` (mature in v8) | `lv_chart_*` (minor API tweaks) |
| Ecosystem/tutorials | Most (Random Nerd, etc.) | Fewer but growing |
| SquareLine export | Supported by default | Requires the v9 template |

**Recommendation**: for new projects, follow the official demo and use **v8.4** (the most tutorials/examples, fewest pitfalls); move up to v9 only if you want new features (e.g., 3D textures, the new scale widget).

## Analysis (Architecture Perspective)

1. **Layering**: driver layer (Arduino_GFX/QSPI) → framework layer (LVGL) → data layer (self-managed) → UI layer (widgets). Keep the data layer independent (ring buffer + sampling timer); the UI only subscribes to render, so neither blocks the other
2. **Chart performance (pending real-device verification)**: lv_chart updates are incremental (only the changed region is redrawn), much faster than full-screen refreshes; combined with a large PSRAM buffer and QSPI bandwidth, "30fps chart animation" is only an **assumption** until it is measured on real hardware in AW-005 (frame rate / touch latency / memory)
3. **Touch interaction is the differentiator**: the AXS15231B integrates touch (I2C 0x3B, up to 2 points; ⚠️ not FT6336U — that is the regular 3.5-inch board), and LVGL's event system (`lv_obj_add_event_cb`) natively supports tapping a chart to pick a point — this is the key to "interactive data"

---

## References

- [LVGL Chart documentation](https://docs.lvgl.io/master/widgets/chart.html)
- [SquareLine Studio tutorial (Zbotic)](https://zbotic.in/squareline-studio-design-ui-for-esp32-tft-with-lvgl-visually/)
- [LVGL Open Widgets](https://lvgl.io/docs/open/widgets/chart)
- [Random Nerd Tutorials LVGL series](https://randomnerdtutorials.com/esp32-tft-lvgl-line-chart/)
