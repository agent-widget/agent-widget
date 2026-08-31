---
title: "数据渲染 Diagram 设计指南"
date: 2026-08-21
status: complete
tags:
  - lvgl
  - data-viz
  - chart
  - design
description: "如何在 ESP32-S3-Touch-LCD-3.5B 上用 LVGL 设计界面渲染数据图表（折线/柱状/仪表盘/触摸交互）"
---
> English version: [data-viz-diagram-design.md](./data-viz-diagram-design.md)


# 数据渲染 Diagram 设计指南

> 创建时间: 2026-08-21
> ⭐ 核心文档：用数据渲染 diagram 的完整方法论 + 可运行代码

---

## 一、设计思路总览

**在 320×480 触摸屏上渲染数据图表，本质是"数据管道 + 渲染管道"两层的组合**：

```
[数据源] → [数据缓冲] → [UI 更新] → [LVGL 渲染] → [屏幕]
  WiFi/API     环形数组      lv_chart/arc/bar    增量绘制     320x480
  传感器         定时采样      事件驱动             QSPI
```

**核心原则**：
1. **数据与 UI 解耦**：数据采集（采样/接收）与渲染分开，采集放定时器/任务，渲染在 `lv_timer_handler()` 主循环
2. **缓冲优先**：数据先入环形缓冲区（如 20~100 点），UI 只读缓冲渲染，不阻塞采集
3. **增量更新**：只更新变化的数据点，不整屏重绘（lv_chart 支持单点更新）

---

## 二、可用图表组件（LVGL widget 一览）

| 组件 | 用途 | 关键 API |
|---|---|---|
| **lv_chart** | 折线图/柱状图/散点图（核心）| `lv_chart_create` / `lv_chart_add_series` / `lv_chart_set_point_count` / `lv_chart_set_range` |
| **lv_arc** | 仪表盘/环形进度 | `lv_arc_create` / `lv_arc_set_value` / `lv_arc_set_rotation` |
| **lv_bar** | 进度条/柱状指示 | `lv_bar_create` / `lv_bar_set_value` |
| **lv_scale** | 坐标轴刻度（v9 新增，v8 用 lv_chart 自带刻度）| `lv_scale_create` / `lv_scale_set_range` |
| **lv_label** | 数值/标题文字 | `lv_label_create` / `lv_label_set_text` |
| **lv_table** | 表格数据 | `lv_table_create` / `lv_table_set_cell_value` |
| **lv_canvas** | 自定义绘制（高级 diagram）| `lv_canvas_create` / `lv_canvas_draw_*` |

---

## 三、折线图（Line Chart）—— 最常用 diagram

### 3.1 经典实现（参考 Random Nerd Tutorials BME280 温度示例）

**数据模型**：环形数组 + 自动缩放范围

```cpp
#define NUM_READINGS 20
float readings[NUM_READINGS] = {0};   // 环形缓冲
float scale_min, scale_max;           // 自动 y 轴范围
```

**创建图表**：

```cpp
// 1. 创建 chart 对象
lv_obj_t *chart = lv_chart_create(lv_scr_act());
lv_obj_set_size(chart, 280, 200);                    // 320x480 屏上留出边距
lv_obj_align(chart, LV_ALIGN_TOP_MID, 0, 40);

// 2. 设置数据点数量（滚动窗口）
lv_chart_set_point_count(chart, NUM_READINGS);

// 3. 添加数据系列（颜色 + 坐标轴）
lv_chart_series_t *ser = lv_chart_add_series(
    chart, lv_palette_main(LV_PALETTE_GREEN), LV_CHART_AXIS_PRIMARY_Y);

// 4. 设置 y 轴范围（自动缩放）
lv_chart_set_range(chart, LV_CHART_AXIS_PRIMARY_Y,
                   (int)(scale_min - 1) * 100, (int)(scale_max + 1) * 100);
```

**更新数据（滚动窗口——新点加入，旧点删除）**：

```cpp
void add_reading(float new_value) {
    // 左移数组（删除最旧）
    for (int i = 0; i < NUM_READINGS - 1; i++)
        readings[i] = readings[i + 1];
    readings[NUM_READINGS - 1] = new_value;

    // 更新图表系列
    for (int i = 0; i < NUM_READINGS; i++)
        ser->y_points[i] = (int32_t)(readings[i] * 100);  // 浮点×100 转整数
    lv_chart_refresh(chart);   // 必须调用才生效
}
```

**定时采样**：

```cpp
void loop() {
    lv_timer_handler();        // LVGL 主循环
    lv_tick_inc(5);
    delay(5);

    if (millis() - last_reading >= 10000) {  // 每 10 秒采一次
        last_reading = millis();
        add_reading(read_sensor());          // 读传感器/API
    }
}
```

### 3.2 触摸交互（点击数据点显示数值）

LVGL chart 自带"按点取数"：注册事件回调，`lv_chart_get_pressed_point()` 返回被按下的数据点索引，再画一个浮动标签显示数值：

```cpp
static void chart_event_cb(lv_event_t *e) {
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t *chart = lv_event_get_target(e);

    if (code == LV_EVENT_DRAW_POST_END) {
        int32_t id = lv_chart_get_pressed_point(chart);
        if (id == LV_CHART_POINT_NONE) return;

        // 取该点的坐标 + 数值
        lv_point_t p;
        lv_chart_series_t *ser = lv_chart_get_series_next(chart, NULL);
        lv_chart_get_point_pos_by_id(chart, ser, id, &p);
        int32_t value = ser->y_points[id];

        // 在点附近绘制数值标签（矩形 + 文字）
        char buf[16];
        lv_snprintf(buf, sizeof(buf), " %3.2f ", (float)value / 100.0);
        lv_draw_rect_dsc_t dsc;
        lv_draw_rect_dsc_init(&dsc);
        dsc.bg_color = lv_color_black();
        dsc.bg_opa = LV_OPA_60;
        // ... 用 lv_draw_rect 在事件层绘制
    }
}
// 注册：lv_obj_add_event_cb(chart, chart_event_cb, LV_EVENT_ALL, NULL);
```

---

## 四、仪表盘（Gauge / lv_arc）—— 单值可视化

适合显示"当前值 + 范围"（温度、电量、使用率）：

```cpp
// 创建弧形仪表
lv_obj_t *arc = lv_arc_create(lv_scr_act());
lv_obj_set_size(arc, 200, 200);
lv_obj_align(arc, LV_ALIGN_CENTER, 0, 0);

// 设为不可拖拽（仅显示）
lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);

// 设置范围（0-100%）
lv_arc_set_range(arc, 0, 100);

// 更新数值
lv_arc_set_value(arc, (int)percentage);   // 每次数据更新调用

// 中间显示数值文字
lv_obj_t *val_label = lv_label_create(lv_scr_act());
lv_label_set_text_fmt(val_label, "%d%%", (int)percentage);
lv_obj_align_to(val_label, arc, LV_ALIGN_CENTER, 0, 0);
```

---

## 五、柱状图（Bar Chart）—— 分类对比

`lv_chart` 切柱状模式：

```cpp
// 切换到柱状模式
lv_chart_set_type(chart, LV_CHART_TYPE_BAR);
// 或混合：LV_CHART_TYPE_LINE | LV_CHART_TYPE_BAR

// 柱宽调整（值越小柱越窄）
lv_obj_set_style_size(chart, 4, LV_PART_ITEMS);

// 更新：同样写 y_points + lv_chart_refresh
```

**示例场景**：一周每日用量（7 根柱）、各传感器读数对比、任务完成率。

---

## 六、完整 Dashboard 布局设计（320×480 竖屏）

```
┌─────────────────────────┐
│ 标题栏 (40px)            │  ← lv_label + 状态图标
│  [首页] [图表] [设置]    │  ← lv_tabview / lv_btnmatrix 页面切换
├─────────────────────────┤
│  当前值大数字 (60px)      │  ← lv_label 大字体 + 单位
│   [=====弧形仪表=====]   │  ← lv_arc 环形进度
├─────────────────────────┤
│  折线图 (200px)          │  ← lv_chart 滚动窗口
│   ▁▂▃▅▇▆▄▃  [touch 取点] │
├─────────────────────────┤
│  柱状图 (100px)          │  ← lv_chart 柱状模式（可切 tab 显示）
│   ▃▇▅▆▂▄                │
└─────────────────────────┘
```

**布局技巧**：
1. **lv_tabview 分页**：一页放"总览"（大数字+仪表），一页放"图表"（折线+柱状），一页放"设置"——避免单页拥挤
2. **lvh 百分比布局**：`lv_obj_set_height(obj, LV_PCT(30))` 让组件随屏自适应
3. **配色**：深色背景（`#1a1a2e`）+ 高亮数据色（绿/青），LVGL 内置 `lv_palette_main()` 取 Material 色板
4. **大字体**：注册自定义字体（lv_font），标题 24px、数值 48px+（可用 `lv_font_montserrat_48` 内置）

---

## 七、数据源接入（WiFi 场景）

### HTTP API 轮询

```cpp
// 用 HTTPClient 拉 JSON → 解析 → 入缓冲
#include <HTTPClient.h>
HTTPClient http;
http.begin("http://192.168.1.100:8080/api/stats");
int code = http.GET();
if (code == 200) {
    String body = http.getString();
    // 解析 JSON（ArduinoJson 库）→ add_reading(value)
}
```

### MQTT 订阅（实时推送）

```cpp
// PubSubClient 订阅 topic，收到消息即更新图表
void mqtt_callback(char *topic, byte *payload, unsigned int len) {
    float value = atof((char *)payload);
    add_reading(value);   // 直接入图表
}
```

### 板载 IMU（本地数据）

QMI8658 6 轴 IMU 直接读加速度/角速度 → 画"姿态曲线"或"步数统计"，无需联网。

---

## 八、性能与内存优化

| 优化点 | 做法 |
|---|---|
| **draw buffer** | 用 PSRAM：`lv_disp_draw_buf_init(&buf, heap_caps_malloc(size, MALLOC_CAP_SPIRAM), NULL, size)`，可开 1/4 屏 |
| **增量刷新** | `lv_chart_set_update_mode(chart, LV_CHART_UPDATE_MODE_SHIFT)` 滚动模式只重绘新区域 |
| **采样频率** | 图表点 20~100 足够（人眼 30fps 上限），别过度采样 |
| **浮点转整数** | chart 用 int32_t，浮点×100/×1000 存，显示时再除（避免 float 频繁转换）|
| **定时器** | 用 `lv_timer_create` 而非 delay 循环，LVGL 统一调度 |
| **字体子集** | 只嵌用到的字符（lv_font_conv 子集化），省 Flash |

---

## 九、我的分析与设计建议

1. **数据管道的架构决策**：把"采样 → 缓冲 → 渲染"做成三个独立模块。缓冲用**环形队列**（RingBuffer），采集任务和渲染主循环通过队列解耦——这是嵌入式数据可视化的标准模式
2. **图表类型选择**：
   - 趋势/时间序列 → **折线图**（lv_chart line）
   - 分类/对比 → **柱状图**（lv_chart bar）
   - 单值/比例 → **仪表盘**（lv_arc）
   - 多指标总览 → **tabview 分页**（避免一屏塞满）
3. **触摸交互是增值点**：官方 chart 支持"按下取点"，配合浮动标签做"查询历史值"体验很好——这是 LCD 屏比普通串口屏的核心优势
4. **LVGL v8 vs v9**：新项目建议 v8.4（官方 demo 同款，教程最多）；除非需要 v9 新 scale 组件
5. **错误方向提醒**：别一上来追求"花哨动画"——先跑通"数据→图表"最小闭环（一个折线图 + 一个仪表盘），再扩展页面和交互

---

## 引用来源

- [Random Nerd Tutorials - ESP32 LVGL 折线图完整代码](https://randomnerdtutorials.com/esp32-tft-lvgl-line-chart/)
- [LVGL Chart 官方文档](https://docs.lvgl.io/master/widgets/chart.html)
- [LVGL Arc 官方文档](https://docs.lvgl.io/master/widgets/arc.html)
- [LVGL Bar 官方文档](https://docs.lvgl.io/master/widgets/bar.html)
- [LVGL Scale 官方文档](https://docs.lvgl.io/master/widgets/scale.html)
- [SquareLine Studio 教程（可视化设计）](https://zbotic.in/squareline-studio-design-ui-for-esp32-tft-with-lvgl-visually/)
- [Waveshare 官方 Arduino demo 代码](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B/Arduino)
