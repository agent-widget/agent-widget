---
title: "Data Visualization Chart Design Guide"
date: 2026-08-21
status: complete
tags:
  - lvgl
  - data-viz
  - chart
  - design
description: "How to design and render data charts (line/bar/gauge/touch interaction) on the ESP32-S3-Touch-LCD-3.5B with LVGL"
---
> Chinese version: [data-viz-diagram-design.zh-CN.md](./data-viz-diagram-design.zh-CN.md)


# Data Visualization Chart Design Guide

> Created: 2026-08-21
> ⭐ Core document: a complete methodology for rendering data-driven charts + runnable code

---

## 1. Design Approach Overview

**Rendering data charts on a 320×480 touchscreen is essentially a combination of two layers: a "data pipeline" and a "render pipeline"**:

```
[Data source] → [Data buffer] → [UI update] → [LVGL render] → [Screen]
  WiFi/API        ring buffer    lv_chart/arc/bar  incremental    320x480
  Sensor          timed sampling  event-driven      drawing        QSPI
```

**Core principles**:
1. **Decouple data from the UI**: separate data acquisition (sampling/receiving) from rendering; run acquisition in a timer/task and render in the `lv_timer_handler()` main loop
2. **Buffer first**: data first goes into a ring buffer (e.g., 20–100 points); the UI only reads the buffer and renders, without blocking acquisition
3. **Incremental updates**: update only the data points that changed instead of redrawing the whole screen (lv_chart supports per-point updates)

---

## 2. Available Chart Widgets (LVGL Widget Overview)

| Widget | Purpose | Key APIs |
|---|---|---|
| **lv_chart** | Line/bar/scatter charts (core) | `lv_chart_create` / `lv_chart_add_series` / `lv_chart_set_point_count` / `lv_chart_set_range` |
| **lv_arc** | Gauges/ring progress | `lv_arc_create` / `lv_arc_set_value` / `lv_arc_set_rotation` |
| **lv_bar** | Progress bars/bar indicators | `lv_bar_create` / `lv_bar_set_value` |
| **lv_scale** | Axis ticks (new in v9; v8 uses lv_chart's built-in ticks) | `lv_scale_create` / `lv_scale_set_range` |
| **lv_label** | Value/title text | `lv_label_create` / `lv_label_set_text` |
| **lv_table** | Table data | `lv_table_create` / `lv_table_set_cell_value` |
| **lv_canvas** | Custom drawing (advanced charts) | `lv_canvas_create` / `lv_canvas_draw_*` |

---

## 3. Line Chart — the Most Common Chart

### 3.1 Classic Implementation (based on the Random Nerd Tutorials BME280 temperature example)

**Data model**: ring array + auto-scaled range

```cpp
#define NUM_READINGS 20
float readings[NUM_READINGS] = {0};   // ring buffer
float scale_min, scale_max;           // auto y-axis range
```

**Creating the chart**:

```cpp
// 1. Create the chart object
lv_obj_t *chart = lv_chart_create(lv_scr_act());
lv_obj_set_size(chart, 280, 200);                    // leave margins on the 320x480 screen
lv_obj_align(chart, LV_ALIGN_TOP_MID, 0, 40);

// 2. Set the number of data points (scrolling window)
lv_chart_set_point_count(chart, NUM_READINGS);

// 3. Add a data series (color + axis)
lv_chart_series_t *ser = lv_chart_add_series(
    chart, lv_palette_main(LV_PALETTE_GREEN), LV_CHART_AXIS_PRIMARY_Y);

// 4. Set the y-axis range (auto-scaling)
lv_chart_set_range(chart, LV_CHART_AXIS_PRIMARY_Y,
                   (int)(scale_min - 1) * 100, (int)(scale_max + 1) * 100);
```

**Updating data (scrolling window — new points in, old points out)**:

```cpp
void add_reading(float new_value) {
    // Shift the array left (drop the oldest)
    for (int i = 0; i < NUM_READINGS - 1; i++)
        readings[i] = readings[i + 1];
    readings[NUM_READINGS - 1] = new_value;

    // Update the chart series
    for (int i = 0; i < NUM_READINGS; i++)
        ser->y_points[i] = (int32_t)(readings[i] * 100);  // float × 100 → integer
    lv_chart_refresh(chart);   // required for the change to take effect
}
```

**Timed sampling**:

```cpp
void loop() {
    lv_timer_handler();        // LVGL main loop
    lv_tick_inc(5);
    delay(5);

    if (millis() - last_reading >= 10000) {  // sample every 10 seconds
        last_reading = millis();
        add_reading(read_sensor());          // read sensor/API
    }
}
```

### 3.2 Touch Interaction (Tap a Data Point to Show Its Value)

LVGL charts support "point picking by press": register an event callback, call `lv_chart_get_pressed_point()` to get the index of the pressed data point, then draw a floating label showing the value:

```cpp
static void chart_event_cb(lv_event_t *e) {
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t *chart = lv_event_get_target(e);

    if (code == LV_EVENT_DRAW_POST_END) {
        int32_t id = lv_chart_get_pressed_point(chart);
        if (id == LV_CHART_POINT_NONE) return;

        // Get the point's coordinates and value
        lv_point_t p;
        lv_chart_series_t *ser = lv_chart_get_series_next(chart, NULL);
        lv_chart_get_point_pos_by_id(chart, ser, id, &p);
        int32_t value = ser->y_points[id];

        // Draw a value label near the point (rectangle + text)
        char buf[16];
        lv_snprintf(buf, sizeof(buf), " %3.2f ", (float)value / 100.0);
        lv_draw_rect_dsc_t dsc;
        lv_draw_rect_dsc_init(&dsc);
        dsc.bg_color = lv_color_black();
        dsc.bg_opa = LV_OPA_60;
        // ... draw with lv_draw_rect on the event layer
    }
}
// Register: lv_obj_add_event_cb(chart, chart_event_cb, LV_EVENT_ALL, NULL);
```

---

## 4. Gauge (lv_arc) — Single-Value Visualization

Good for showing "current value + range" (temperature, battery level, utilization):

```cpp
// Create the arc gauge
lv_obj_t *arc = lv_arc_create(lv_scr_act());
lv_obj_set_size(arc, 200, 200);
lv_obj_align(arc, LV_ALIGN_CENTER, 0, 0);

// Make it non-draggable (display only)
lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);

// Set the range (0-100%)
lv_arc_set_range(arc, 0, 100);

// Update the value
lv_arc_set_value(arc, (int)percentage);   // call on every data update

// Show the value as text in the center
lv_obj_t *val_label = lv_label_create(lv_scr_act());
lv_label_set_text_fmt(val_label, "%d%%", (int)percentage);
lv_obj_align_to(val_label, arc, LV_ALIGN_CENTER, 0, 0);
```

---

## 5. Bar Chart — Categorical Comparison

Switch `lv_chart` into bar mode:

```cpp
// Switch to bar mode
lv_chart_set_type(chart, LV_CHART_TYPE_BAR);
// Or mixed: LV_CHART_TYPE_LINE | LV_CHART_TYPE_BAR

// Adjust bar width (smaller value = narrower bars)
lv_obj_set_style_size(chart, 4, LV_PART_ITEMS);

// Update: write y_points the same way + lv_chart_refresh
```

**Example scenarios**: daily usage over a week (7 bars), comparing readings across sensors, task completion rates.

---

## 6. Full Dashboard Layout Design (320×480 Portrait)

```
┌─────────────────────────┐
│ Title bar (40px)        │  ← lv_label + status icon
│ [Home] [Charts] [Setup] │  ← lv_tabview / lv_btnmatrix page switching
├─────────────────────────┤
│ Current value (60px)    │  ← large lv_label + unit
│ [=====Arc gauge=====]   │  ← lv_arc ring progress
├─────────────────────────┤
│ Line chart (200px)      │  ← lv_chart scrolling window
│  ▁▂▃▅▇▆▄▃  [touch pick] │
├─────────────────────────┤
│ Bar chart (100px)       │  ← lv_chart bar mode (switchable via tabs)
│  ▃▇▅▆▂▄                 │
└─────────────────────────┘
```

**Layout tips**:
1. **Use lv_tabview pages**: one page for "Overview" (big number + gauge), one for "Charts" (line + bar), one for "Settings" — avoids crowding a single page
2. **Percent-based layout**: `lv_obj_set_height(obj, LV_PCT(30))` lets widgets adapt to the screen
3. **Color scheme**: dark background (`#1a1a2e`) + bright data colors (green/cyan); LVGL's built-in `lv_palette_main()` pulls from the Material palette
4. **Large fonts**: register a custom font (lv_font); titles 24px, values 48px+ (the built-in `lv_font_montserrat_48` works)

---

## 7. Data Source Integration (Wi-Fi Scenarios)

### HTTP API Polling

```cpp
// Pull JSON with HTTPClient → parse → push into the buffer
#include <HTTPClient.h>
HTTPClient http;
http.begin("http://192.168.1.100:8080/api/stats");
int code = http.GET();
if (code == 200) {
    String body = http.getString();
    // Parse JSON (ArduinoJson library) → add_reading(value)
}
```

### MQTT Subscription (Real-Time Push)

```cpp
// Subscribe with PubSubClient; update the chart on every received message
void mqtt_callback(char *topic, byte *payload, unsigned int len) {
    float value = atof((char *)payload);
    add_reading(value);   // feed directly into the chart
}
```

### On-Board IMU (Local Data)

The QMI8658 6-axis IMU can be read directly for acceleration/angular velocity → plot "attitude curves" or "step counts" with no network needed.

---

## 8. Performance and Memory Optimization

| Optimization | Approach |
|---|---|
| **draw buffer** | Use PSRAM: `lv_disp_draw_buf_init(&buf, heap_caps_malloc(size, MALLOC_CAP_SPIRAM), NULL, size)`; a 1/4-screen buffer is achievable |
| **Incremental refresh** | `lv_chart_set_update_mode(chart, LV_CHART_UPDATE_MODE_SHIFT)` scroll mode redraws only the new region |
| **Sampling rate** | 20–100 chart points are enough (the human eye tops out around 30fps); don't over-sample |
| **Float to integer** | charts use int32_t; store floats ×100/×1000 and divide when displaying (avoid frequent float conversions) |
| **Timers** | use `lv_timer_create` instead of delay loops; LVGL schedules everything |
| **Font subsetting** | embed only the characters used (subset with lv_font_conv) to save Flash |

---

## 9. Analysis and Design Recommendations

1. **Architecture decision for the data pipeline**: build "sampling → buffering → rendering" as three independent modules. Buffer with a **ring queue** (RingBuffer); the acquisition task and the rendering main loop are decoupled through the queue — this is the standard pattern for embedded data visualization
2. **Chart type selection**:
   - Trend/time series → **line chart** (lv_chart line)
   - Categorical/comparison → **bar chart** (lv_chart bar)
   - Single value/ratio → **gauge** (lv_arc)
   - Multi-metric overview → **tabview pages** (avoid cramming one screen)
3. **Touch interaction is a value-add**: the official chart supports "press to pick a point"; paired with a floating label it makes a great "look up historical values" experience — this is the key advantage of an LCD screen over an ordinary serial screen
4. **LVGL v8 vs v9**: for new projects, recommend v8.4 (same version as the official demo, most tutorials); move to v9 only if you need its new scale widget
5. **A caution about direction**: don't chase "fancy animations" first — get the minimal "data → chart" loop working (one line chart + one gauge), then expand pages and interactions

---

## References

- [Random Nerd Tutorials — ESP32 LVGL line chart full code](https://randomnerdtutorials.com/esp32-tft-lvgl-line-chart/)
- [LVGL Chart official documentation](https://docs.lvgl.io/master/widgets/chart.html)
- [LVGL Arc official documentation](https://docs.lvgl.io/master/widgets/arc.html)
- [LVGL Bar official documentation](https://docs.lvgl.io/master/widgets/bar.html)
- [LVGL Scale official documentation](https://docs.lvgl.io/master/widgets/scale.html)
- [SquareLine Studio tutorial (visual design)](https://zbotic.in/squareline-studio-design-ui-for-esp32-tft-with-lvgl-visually/)
- [Waveshare official Arduino demo code](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B/Arduino)
